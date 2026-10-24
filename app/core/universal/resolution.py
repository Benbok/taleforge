"""Short atomic execution of previously admitted numeric profiles. No model calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field
from sqlalchemy import func, select, update

from app.core.campaigns import AccessDenied, NotFound
from app.core.universal.profiles import actor_row, get_profile, load_actor, save_actor
from app.db.models import Campaign, Character, Event, HeroAbility, RuntimeProfile, Seat
from app.rules.universal.contracts import ClosedModel, Count
from app.rules.universal.mechanics import derive, starting_defense_bonuses
from app.rules.universal.profiles import (
    ActionOutcome,
    EffectOutcome,
    EffectSpec,
    ProfileSpec,
    bind_resistance,
    damage_amount,
    resolve_attack,
    resolve_check,
    resolve_resistance,
    resource_cost,
    restore,
    validate_profile,
)


class ActionRef(ClosedModel):
    profile_id: str = Field(min_length=1, max_length=128)
    revision: Count = Field(ge=1)


class ProposedAction(ClosedModel):
    ref: ActionRef
    actor_id: str
    targets: list[str] = Field(default_factory=list, max_length=100)
    profile: ProfileSpec
    operations: list[EffectSpec] = Field(default_factory=list, max_length=16)
    reason: str = Field(default="", max_length=4000)
    difficulty: int = Field(default=12, ge=1, le=40, strict=True)
    edge: Literal["normal", "advantage", "disadvantage"] = "normal"
    critical_failure_consequence: Literal["self_damage_1"] = "self_damage_1"


@dataclass
class ResolutionContext:
    session: object
    campaign_id: str
    user_id: str
    seat_id: str
    actor_id: str
    dice: object
    allowed_target_ids: frozenset[str] | None = None


async def resolve_action(ctx, proposal: ProposedAction, request_key: str) -> ActionOutcome:
    if not request_key or len(request_key) > 64:
        return ActionOutcome(status="denied")
    try:
        proposal = ProposedAction.model_validate(proposal.model_dump())
        async with ctx.session.begin_nested():
            return await _execute(ctx, proposal, request_key)
    except (AccessDenied, NotFound, ValueError):
        return ActionOutcome(status="denied")


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
    row = await actor_row(s, ctx.campaign_id, p.actor_id, refresh=True)
    seat = await s.get(Seat, ctx.seat_id, populate_existing=True)
    if (
        p.actor_id != ctx.actor_id
        or not isinstance(row, Character)
        or row.seat_id != ctx.seat_id
        or row.status not in {"active", "approved"}
        or seat is None
        or seat.campaign_id != ctx.campaign_id
        or ctx.user_id not in {seat.user_id, seat.stand_in_user_id}
    ):
        raise AccessDenied("actor seat is not controlled by this user")
    previous = await s.scalar(select(Event).where(Event.campaign_id == ctx.campaign_id, Event.idempotency_key == key))
    if previous:
        if (
            previous.tool != "universal_action"
            or previous.actor_id != p.actor_id
            or previous.payload["proposal"] != p.model_dump(mode="json")
        ):
            raise AccessDenied("idempotency key already belongs to another action")
        return ActionOutcome.model_validate(previous.payload["outcome"]).model_copy(update={"status": "repeated"})
    profile = await get_profile(s, ctx.campaign_id, p.ref.profile_id, p.ref.revision)
    latest = await s.scalar(
        select(func.max(RuntimeProfile.revision)).where(
            RuntimeProfile.campaign_id == ctx.campaign_id, RuntimeProfile.ref == p.ref.profile_id
        )
    )
    # A learned ability pins its immutable rules even as new admissions evolve.
    learned = await s.scalar(
        select(HeroAbility).where(
            HeroAbility.campaign_id == ctx.campaign_id,
            HeroAbility.character_id == p.actor_id,
            HeroAbility.profile_ref == p.ref.profile_id,
            HeroAbility.profile_revision == p.ref.revision,
        )
    )
    pinned = learned is not None and learned.definition == profile.model_dump(mode="json")
    if (
        (latest != p.ref.revision and not pinned)
        or profile != validate_profile(p.profile)
        or profile.id != p.ref.profile_id
        or p.operations != profile.effects
    ):
        raise AccessDenied("stale profile or operations outside admitted budget")
    if profile.duration != 1 or any(e.clock != "immediate" for e in profile.effects):
        raise AccessDenied("scheduled effects require the combat duration runtime")
    if profile.item_id is not None or profile.use_conditions:
        raise AccessDenied("item and conditional profiles require explicit runtime support")
    sheet, resources = await load_actor(s, ctx.campaign_id, p.actor_id)
    if profile.trained and profile.id not in sheet.trained:
        raise AccessDenied("training must be confirmed in the saved sheet")
    if profile.resource_key is not None and profile.resource_key != profile.attribute:
        raise AccessDenied("paid energy must match the acting attribute")
    if profile.use_kind == "weapon_basic":
        weapon = sheet.starting_equipment.weapon if sheet.starting_equipment else None
        if weapon is None or profile.attribute != weapon.attack_ability or profile.base_dice != weapon.damage_dice:
            raise AccessDenied("basic attack requires admitted equipped starting weapon")
    ids = p.targets or ([p.actor_id] if profile.kind == "narrative" else [])
    if not ids or len(ids) != len(set(ids)) or len(ids) != profile.target_count:
        raise AccessDenied("target count differs from paid profile")
    targets = {}
    for target in ids:
        target_row = await actor_row(s, ctx.campaign_id, target, refresh=True)
        if ctx.allowed_target_ids is not None and target not in ctx.allowed_target_ids and target != p.actor_id:
            raise AccessDenied("target outside admitted scene")
        if target_row.location_id != row.location_id:
            raise AccessDenied("target is outside actor location")
        targets[target] = await load_actor(s, ctx.campaign_id, target)
    cost = resource_cost(profile, sheet.level)
    energy = profile.resource_key or (profile.attribute if profile.attribute != "con" else None)
    if cost and (energy is None or resources.energies[energy] < cost):
        raise AccessDenied("insufficient energy")
    # Fix all resistance DCs before any dice are rolled.
    effects = []
    for effect in profile.effects:
        if effect.source_id and effect.source_id != p.actor_id or effect.target_id and effect.target_id not in ids:
            raise AccessDenied("foreign effect source or target")
        resistance = (
            bind_resistance(effect.resistance, getattr(sheet.abilities, effect.resistance.source_attribute))
            if effect.resistance
            else None
        )
        effects.append(effect.model_copy(update={"resistance": resistance}))
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
