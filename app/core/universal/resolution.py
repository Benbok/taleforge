"""Short atomic execution of previously admitted numeric profiles. No model calls."""

from __future__ import annotations

from sqlalchemy import select, update

from app.core.campaigns import AccessDenied, NotFound
from app.core.universal.contracts import ProposedAction
from app.core.universal.contracts import ActionRef as ActionRef
from app.core.universal.contracts import ResolutionContext as ResolutionContext
from app.core.universal.profiles import save_actor
from app.core.universal.validation import authorize_actor, validate_action
from app.db.models import Campaign, Event
from app.rules.universal.failures import ActionValidationError, action_failure, reject
from app.rules.universal.mechanics import derive, starting_defense_bonuses
from app.rules.universal.profiles import (
    ActionOutcome,
    EffectOutcome,
    EffectSpec,
    damage_amount,
    resolve_attack,
    resolve_check,
    resolve_resistance,
    restore,
)


async def resolve_action(ctx, proposal: ProposedAction, request_key: str) -> ActionOutcome:
    if not request_key or len(request_key) > 64:
        return ActionOutcome(status="denied", failure=action_failure("invalid_proposal"))
    try:
        proposal = ProposedAction.model_validate(proposal.model_dump())
        async with ctx.session.begin_nested():
            return await _execute(ctx, proposal, request_key)
    except ActionValidationError as exc:
        return ActionOutcome(status="denied", failure=exc.failure)
    except (AccessDenied, NotFound, ValueError):
        return ActionOutcome(status="denied", failure=action_failure("invalid_proposal"))


class _RecordingDice:
    def __init__(self, dice):
        self.dice = dice
        self.rolls = []

    def d20(self):
        result = self.dice.d20()
        self.rolls.append(result)
        return result

    def die(self, sides):
        result = self.dice.die(sides)
        self.rolls.append(result)
        return result


async def _execute(ctx, p, key):
    s = ctx.session
    dice = _RecordingDice(ctx.dice)
    # Serialize campaign runtime and receipts before reading mutable state (including SQLite).
    await s.execute(
        update(Campaign).where(Campaign.id == ctx.campaign_id).values(world_revision=Campaign.world_revision)
    )
    await authorize_actor(ctx, p, require_active=False)
    previous = await s.scalar(select(Event).where(Event.campaign_id == ctx.campaign_id, Event.idempotency_key == key))
    if previous:
        if (
            previous.tool != "universal_action"
            or previous.actor_id != p.actor_id
            or previous.payload["proposal"] != p.model_dump(mode="json")
        ):
            reject("invalid_proposal")
        return ActionOutcome.model_validate(previous.payload["outcome"]).model_copy(update={"status": "repeated"})
    state = await validate_action(ctx, p)
    sheet, resources, profile = state.sheet, state.resources, state.profile
    targets, effects, cost, energy = state.targets, state.effects, state.cost, state.energy
    if cost:
        resources.energies[energy] -= cost
    # Shared object for self target prevents damage/restoration overwriting the debit.
    if p.actor_id in targets:
        targets[p.actor_id] = (sheet, resources)
    result = ActionOutcome(success=True, cost=cost)
    for target, (target_sheet, target_resources) in targets.items():
        if profile.kind == "damage":
            hit = resolve_attack(dice, sheet, derive(target_sheet, starting_defense_bonuses(target_sheet)).ac, profile)
            if result.natural is None:
                result.natural, result.total, result.critical, result.critical_failure = (
                    hit.natural,
                    hit.total,
                    hit.critical,
                    hit.critical_failure,
                )
            result.rolls.extend(hit.rolls)
            result.success = result.success and hit.success
            amount = min(target_resources.hp, hit.damage)
            result.damage += amount
            target_resources.hp -= amount
            result.effect_outcomes.append(
                EffectOutcome(effect_id="primary", target_id=target, applied=hit.success and amount > 0)
            )
            if not hit.success:
                continue
        elif profile.kind == "heal":
            before = target_resources.hp
            target_resources.hp = restore(
                before,
                derive(target_sheet, starting_defense_bonuses(target_sheet)).hp_max,
                damage_amount(dice, sheet, profile),
            )
            result.effect_outcomes.append(
                EffectOutcome(effect_id="primary", target_id=target, applied=target_resources.hp > before)
            )
        elif profile.kind in {"narrative", "check"}:
            check = resolve_check(
                dice, getattr(sheet.abilities, profile.attribute), profile.trained, p.difficulty, p.edge
            )
            result.success = result.success and check.success
            result.natural, result.total = check.natural, check.total
            result.rolls.extend(check.rolls)
            result.effect_outcomes.append(EffectOutcome(effect_id="primary", target_id=target, applied=check.success))
            if not check.success:
                continue
        for effect in effects:
            if effect.target_id and effect.target_id != target:
                continue
            applied = effect.model_copy(update={"source_id": p.actor_id, "target_id": target})
            outcome = (
                resolve_resistance(
                    dice,
                    target,
                    effect.id,
                    getattr(target_sheet.abilities, effect.resistance.attribute),
                    effect.resistance,
                )
                if effect.resistance
                else EffectOutcome(effect_id=effect.id, target_id=target, applied=True)
            )
            result.effect_outcomes.append(outcome)
            if outcome.natural:
                result.rolls.append(outcome.natural)
            if not outcome.applied:
                continue
            if effect.kind == "damage":
                amount = min(target_resources.hp, damage_amount(dice, sheet, profile))
                target_resources.hp -= amount
                result.damage += amount
                applied.value = amount
                outcome.applied = amount > 0
            elif effect.kind == "heal":
                before = target_resources.hp
                target_resources.hp = restore(
                    before,
                    derive(target_sheet, starting_defense_bonuses(target_sheet)).hp_max,
                    damage_amount(dice, sheet, profile),
                )
                applied.value = target_resources.hp - before
                outcome.applied = applied.value > 0
            elif effect.kind != "narrative":
                target_resources.effects.append(applied)
            result.public_effects.append(applied)
    if result.critical_failure:
        # Fixed before rolling, bounded and saved in the same receipt as the miss.
        harm = min(1, resources.hp)
        resources.hp -= harm
        result.public_effects.append(
            EffectSpec(id="critical-failure", source_id=p.actor_id, target_id=p.actor_id, kind="damage", value=harm)
        )
    await save_actor(s, ctx.campaign_id, p.actor_id, sheet, resources)
    for target, (target_sheet, target_resources) in targets.items():
        await save_actor(s, ctx.campaign_id, target, target_sheet, target_resources)
    result.rolls = dice.rolls
    event = Event(
        campaign_id=ctx.campaign_id,
        tool="universal_action",
        actor_id=p.actor_id,
        idempotency_key=key,
        payload={"proposal": p.model_dump(mode="json"), "outcome": result.model_dump(mode="json")},
        dice=result.rolls,
    )
    s.add(event)
    await s.flush()
    from app.core.universal.discovery import record_realized_ability

    await record_realized_ability(s, p.actor_id, p, result, event.id)
    await s.flush()
    return result
