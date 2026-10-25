"""One serialized V2 action: spend, effects, time, receipt and learning. No model I/O."""

import hashlib

from sqlalchemy import select

from app.core.campaigns import AccessDenied, NotFound
from app.core.universal.clock import clock_view, complete_step, lock_campaign
from app.core.universal.definitions import admit_definition
from app.core.universal.discovery import learned_abilities
from app.core.universal.effects import dismiss_effect, start_effect
from app.core.universal.interpretation import validate_exploration
from app.core.universal.objects import apply_object_operation, introduce_object
from app.core.universal.profiles import save_actor
from app.core.universal.validation import authorize_actor
from app.db.models import Event, HeroAbility, Message
from app.rules.universal.exploration import TIMED_KINDS, EffectChange, ExplorationAction, ExplorationOutcome
from app.rules.universal.failures import action_failure
from app.rules.universal.profiles import CheckProof, DieProof, resolve_check

OBJECT_KINDS = {"create_object", "take", "place", "give", "fill", "pour", "empty", "consume"}


def public_exploration_facts(outcome):
    data = outcome.model_dump(mode="json")
    data["changes"] = [c.model_dump(mode="json") for c in outcome.changes if not c.private]
    data.pop("private_effects", None)
    return data


async def record_exploration_ability(session, actor, action, outcome, event):
    if not outcome.success or action.definition.source != "supernatural":
        return None
    if (
        event.actor_id != actor.id
        or event.campaign_id != actor.campaign_id
        or event.payload.get("outcome") != outcome.model_dump(mode="json")
    ):
        raise AccessDenied("Обучение требует сохранённой квитанции")
    definition = await admit_definition(session, actor.campaign_id, action.definition)
    learned = await session.scalar(
        select(HeroAbility).where(
            HeroAbility.character_id == actor.id,
            HeroAbility.profile_ref == definition.id,
        )
    )
    if learned is None:
        learned = HeroAbility(
            campaign_id=actor.campaign_id,
            character_id=actor.id,
            profile_ref=definition.id,
            profile_revision=definition.revision,
            name=definition.name,
            definition=definition.model_dump(mode="json"),
            source_event_id=event.id,
        )
        session.add(learned)
        await session.flush()
    actor.resources = {**actor.resources, "learned_abilities": await learned_abilities(session, actor.id)}
    return learned


async def _objects(ctx, action, event):
    bindings = {}
    # Evidence was admitted separately; do not accept evidence supplied by the player's action.
    for spec in action.introductions:
        if spec.template == "observer":
            from app.core.universal.perception import introduce_observer

            row = await introduce_observer(ctx, spec)
        else:
            row = await introduce_object(ctx.session, ctx.campaign_id, spec, spec.evidence_quote, actor_id=ctx.actor_id)
        bindings[f"intro:{spec.ref}"] = row.id
    changes = []
    for index, op in enumerate(action.operations):
        if op.kind not in OBJECT_KINDS:
            continue
        updates = {
            field: bindings.get(getattr(op, field), getattr(op, field))
            for field in ("object_id", "source_id", "target_id", "recipient_id")
        }
        actual = op.model_copy(update=updates)
        change = await apply_object_operation(ctx, actual, event, component=str(index))
        bindings[f"created:{index}"] = change.subject_id
        changes.append(change)
    return changes


async def resolve_exploration(ctx, action, request_key):
    try:
        action = ExplorationAction.model_validate(action.model_dump())
        if not request_key or len(request_key) > 64 or request_key != action.source_message_id:
            raise ValueError("Неверный ключ сообщения")
        async with ctx.session.begin_nested():
            return await _execute(ctx, action, request_key)
    except (ValueError, AccessDenied, NotFound):
        return ExplorationOutcome(status="denied", failure=action_failure("invalid_proposal"))


async def _execute(ctx, action, key):
    s = ctx.session
    await lock_campaign(s, ctx.campaign_id)
    await authorize_actor(ctx, action, require_active=False)
    previous = await s.scalar(select(Event).where(Event.campaign_id == ctx.campaign_id, Event.idempotency_key == key))
    if previous:
        if (
            previous.tool != "universal_action"
            or previous.actor_id != action.actor_id
            or previous.payload.get("proposal") != action.model_dump(mode="json")
        ):
            raise ValueError("Ключ квитанции уже занят")
        return ExplorationOutcome.model_validate(previous.payload["outcome"]).model_copy(update={"status": "repeated"})
    source = await s.get(Message, action.source_message_id)
    if (
        source is None
        or source.campaign_id != ctx.campaign_id
        or source.seat_id != ctx.seat_id
        or source.kind not in {"action", "speech", "whisper"}
        or hashlib.sha256(source.content.encode()).hexdigest() != action.source_hash
    ):
        raise AccessDenied("Действие не связано с исходным сообщением")
    await validate_exploration(ctx, action)
    # Validate compound material/liquid operations before any die is consumed. The savepoint
    # simulates the complete object sequence and is always rolled back, including introductions.
    if action.introductions or any(op.kind in OBJECT_KINDS for op in action.operations):
        preview = await s.begin_nested()
        try:
            trial = Event(campaign_id=ctx.campaign_id, actor_id=action.actor_id, tool="universal_action", payload={})
            s.add(trial)
            await s.flush()
            await _objects(ctx, action, trial)
        finally:
            await preview.rollback()
    state = await validate_exploration(ctx, action)
    now = int((await clock_view(s, ctx.campaign_id))["game_seconds"])
    result = ExplorationOutcome(success=True, cost=action.cost, elapsed_game_seconds=action.elapsed_game_seconds)
    if action.cost:
        state.resources.energies[action.attribute] -= action.cost
        await save_actor(s, ctx.campaign_id, action.actor_id, state.sheet, state.resources)
    if action.resolution == "check":
        check = resolve_check(
            ctx.dice, getattr(state.sheet.abilities, action.attribute), False, action.difficulty, action.edge
        )
        for field in ("success", "natural", "total", "rolls", "critical", "critical_failure"):
            setattr(result, field, getattr(check, field))
        result.draws = [DieProof(sides=20, value=v) for v in result.rolls]
        result.checks = [
            CheckProof(
                target_id=action.actor_id,
                attribute=action.attribute,
                natural=check.natural,
                total=check.total,
                modifier=check.total - check.natural,
                difficulty=action.difficulty,
                success=check.success,
                mode=action.edge,
                critical=check.critical,
                critical_failure=check.critical_failure,
            )
        ]
    event = Event(
        campaign_id=ctx.campaign_id, actor_id=action.actor_id, tool="universal_action", idempotency_key=key, payload={}
    )
    s.add(event)
    await s.flush()
    if result.success:
        result.changes.extend(await _objects(ctx, action, event))
        created = iter([c for c in result.changes if c.kind == "object_created"])
        for index, op in enumerate(action.operations):
            target = action.actor_id
            if op.kind == "create_object":
                target = next(created).subject_id
            if op.kind in TIMED_KINDS or op.lifetime == "timed":
                context = {
                    "requires_form": op.kind == "camouflage" and any(o.kind == "change_form" for o in action.operations)
                }
                effect = await start_effect(
                    s,
                    ctx.campaign_id,
                    action.actor_id,
                    target,
                    event.id,
                    str(index),
                    op,
                    now + action.elapsed_game_seconds,
                    action.definition.duration_seconds,
                    context=context,
                )
                label = {
                    "change_form": "Форма куста",
                    "camouflage": "Маскировка",
                    "illumination": "Освещение",
                    "hold_breath": "Задержка дыхания",
                }.get(op.kind, "Временный эффект")
                result.changes.append(
                    EffectChange(
                        kind=op.kind,
                        subject_id=target,
                        description=f"{label}: действует {action.definition.duration_seconds} с.",
                        data=dict(effect_id=effect.id, duration_seconds=str(action.definition.duration_seconds)),
                    )
                )
            elif op.kind == "cosmetic":
                result.changes.append(
                    EffectChange(
                        kind="cosmetic",
                        subject_id=target,
                        description="Косметическое волшебство проявилось без дополнительных преимуществ.",
                    )
                )
            elif op.kind == "dismiss":
                result.changes.extend(await dismiss_effect(s, ctx.campaign_id, action.actor_id, op.effect_id or ""))
    step = await complete_step(s, ctx.campaign_id, key, action.elapsed_game_seconds)
    result.game_seconds = int(step.ended_seconds)
    result.changes.extend(EffectChange.model_validate(c) for c in step.changes)
    result.description = " ".join(c.description for c in result.changes if not c.private) or (
        "Проверка успешна; новых подтверждённых наблюдений нет."
        if result.success
        else "Попытка не удалась; задуманные эффекты не возникли."
    )
    event.payload = dict(
        schema_version=2, proposal=action.model_dump(mode="json"), outcome=result.model_dump(mode="json")
    )
    learned = await record_exploration_ability(s, state.actor, action, result, event)
    if learned:
        result.ability_ref = learned.profile_ref
        event.payload = {**event.payload, "outcome": result.model_dump(mode="json")}
    await s.flush()
    return result
