"""One serialized V2 action: spend, effects, time, receipt and learning. No model I/O."""

import hashlib

from sqlalchemy import select

from app.core.campaigns import AccessDenied, NotFound
from app.core.universal.clock import clock_view, complete_step, lock_campaign
from app.core.universal.definitions import admit_definition
from app.core.universal.discovery import learned_abilities
from app.core.universal.effects import dismiss_effect, start_effect
from app.core.universal.interpretation import validate_exploration
from app.core.universal.journal import record_journal
from app.core.universal.objects import apply_object_operation, introduce_object
from app.core.universal.profiles import save_actor
from app.core.universal.validation import authorize_actor
from app.db.models import Entity, Event, HeroAbility, Message
from app.rules.universal.exploration import TIMED_KINDS, EffectChange, ExplorationAction, ExplorationOutcome
from app.rules.universal.failures import action_failure
from app.rules.universal.profiles import CheckProof, DieProof, resolve_check

OBJECT_KINDS = {"create_object", "take", "place", "give", "fill", "pour", "empty", "consume", "move", "command"}


def _touches_objects(op):
    """Plain walking moves only the hero; walking over a remembered structure is an object operation."""
    return op.kind in OBJECT_KINDS and (op.kind != "move" or bool(op.object_id))


def public_exploration_facts(outcome):
    data = outcome.model_dump(mode="json")
    data["changes"] = [c.model_dump(mode="json") for c in outcome.changes if not c.private]
    data.pop("private_effects", None)
    return data


async def record_exploration_ability(session, actor, action, outcome, event):
    if (
        not outcome.success
        or not outcome.realized
        or action.definition.source != "supernatural"
        or any(not e.applied for e in outcome.effect_outcomes)
    ):
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


async def _introductions(ctx, action):
    bindings = {}
    # Evidence was admitted separately; do not accept evidence supplied by the player's action.
    for spec in action.introductions:
        if spec.template == "observer":
            from app.core.universal.perception import introduce_observer

            row = await introduce_observer(ctx, spec)
        else:
            row = await introduce_object(ctx.session, ctx.campaign_id, spec, spec.evidence_quote, actor_id=ctx.actor_id)
        bindings[f"intro:{spec.ref}"] = row.id
    return bindings


async def _objects(ctx, action, event):
    bindings = await _introductions(ctx, action)
    changes = []
    for index, op in enumerate(action.operations):
        if not _touches_objects(op):
            continue
        updates = {
            field: bindings.get(getattr(op, field), getattr(op, field))
            for field in ("object_id", "source_id", "target_id", "recipient_id")
        }
        actual = op.model_copy(update=updates)
        if actual.kind == "consume":
            item = await ctx.session.get(Entity, actual.object_id or "")
            if item is not None and "universal_item" in item.state:
                from app.core.universal.inventory import consume

                used = await consume(
                    ctx.session,
                    ctx.campaign_id,
                    ctx.actor_id,
                    item.id,
                    actual.target_id or action.targets[0],
                    f"item-{event.id}-{index}",
                )
                changes.extend(used.changes)
                continue
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
            or ExplorationAction.model_validate(previous.payload["proposal"]).model_dump(mode="json")
            != action.model_dump(mode="json")
        ):
            raise ValueError("Ключ квитанции уже занят")
        return ExplorationOutcome.model_validate(previous.payload["outcome"]).model_copy(update={"status": "repeated"})
    source = await s.get(Message, ctx.parent_source_id if ctx.npc_reply else action.source_message_id)
    if (
        source is None
        or source.campaign_id != ctx.campaign_id
        or source.seat_id != ctx.seat_id
        or source.kind not in {"action", "speech", "whisper"}
        or hashlib.sha256(source.content.encode()).hexdigest() != action.source_hash
    ):
        raise AccessDenied("Действие не связано с исходным сообщением")
    await validate_exploration(ctx, action)
    if action.introductions:
        from app.core.universal.perception import established_evidence

        evidence = await established_evidence(s, ctx.campaign_id, ctx.actor_id)
        if any(spec.evidence_quote not in evidence for spec in action.introductions):
            raise ValueError("Основание предмета или наблюдателя больше не доступно")
    # Validate compound material/liquid operations before any die is consumed. The savepoint
    # simulates the complete object sequence and is always rolled back, including introductions.
    if action.introductions or any(_touches_objects(op) for op in action.operations):
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
    from app.core.universal.combat_actions import COMBAT_KINDS, combat_action

    if action.introductions:
        await _introductions(ctx, action)
    if result.success and any(op.kind in COMBAT_KINDS for op in action.operations):
        await combat_action(ctx, action, event, result, now)
    if result.success:
        result.changes.extend(await _objects(ctx, action, event))
        created = iter([c for c in result.changes if c.kind == "object_created"])
        for index, op in enumerate(action.operations):
            if op.kind in COMBAT_KINDS:
                continue
            target = action.actor_id
            if op.kind == "move" and op.destination_id:
                from app.core.universal.travel import move_hero

                result.changes.append(await move_hero(ctx, op.destination_id))
                continue
            if op.kind == "move" and not op.object_id:
                result.changes.append(
                    EffectChange(
                        kind="moved_within_scene",
                        subject_id=action.actor_id,
                        description="Герой переместился в пределах текущего места; "
                        "переход в другую локацию не выполнялся.",
                    )
                )
                continue
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
                if op.kind == "free_effect":
                    label = op.label or "Эффект"
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
    if not ctx.defer_step:
        step = await complete_step(s, ctx.campaign_id, key, action.elapsed_game_seconds, dice=ctx.dice)
        result.game_seconds = int(step.ended_seconds)
        result.changes.extend(EffectChange.model_validate(c) for c in step.changes)
    else:
        result.game_seconds = now + action.elapsed_game_seconds
    from app.core.universal.perception import assess_detection, observe_known_scene

    if result.success:
        for op in action.operations:
            if op.kind == "observe":
                from app.core.universal.travel import remember_place

                await remember_place(ctx, state.actor)
                result.changes.extend(await observe_known_scene(ctx, op.aspect))
    for observer in await s.scalars(
        select(Entity).where(
            Entity.campaign_id == ctx.campaign_id,
            Entity.kind == "creature",
            Entity.location_id == state.actor.location_id,
        )
    ):
        if not ctx.npc_reply and "exploration_observer" in observer.state:
            detection = await assess_detection(ctx, observer.id, action.actor_id, key, at_seconds=result.game_seconds)
            result.changes.append(detection)
            if not detection.private and detection.data.get("natural") is not None:
                data = detection.data
                result.rolls.extend(data["rolls"])
                result.draws.extend(DieProof(sides=20, value=v) for v in data["rolls"])
                result.checks.append(
                    CheckProof(
                        target_id=action.actor_id,
                        effect_id="detection",
                        attribute="dex",
                        natural=data["natural"],
                        total=int(data["total"]),
                        modifier=int(data["total"]) - data["natural"],
                        difficulty=None,
                        success=data["concealed"],
                        mode=data["mode"],
                        critical=data["critical"],
                        critical_failure=data["critical_failure"],
                    )
                )
    from app.core.universal.effects import scope_changes

    result.changes = await scope_changes(ctx, result.changes)
    result.description = " ".join(c.description for c in result.changes if not c.private) or _outcome_hint(
        action, result
    )
    if result.success:
        await _journal_unusual(ctx, action)
    event.payload = dict(
        schema_version=2, proposal=action.model_dump(mode="json"), outcome=result.model_dump(mode="json")
    )
    learned = None if ctx.npc_reply else await record_exploration_ability(s, state.actor, action, result, event)
    if learned:
        result.ability_ref = learned.profile_ref
        event.payload = {**event.payload, "outcome": result.model_dump(mode="json")}
    await s.flush()
    return result


def _outcome_hint(action, result):
    """With nothing changed in the world, the outcome the model wrote for this result is all there is to tell."""
    hints = action.check_outcomes
    if action.resolution == "check" and hints is not None:
        if result.success:
            text = (hints.critical_success if result.critical else None) or hints.success
        else:
            text = (hints.critical_failure if result.critical_failure else None) or hints.failure
        if text:
            return text
    return (
        "Проверка успешна; новых подтверждённых наблюдений нет."
        if result.success
        else "Попытка не удалась; задуманные эффекты не возникли."
    )


async def _journal_unusual(ctx, action):
    """Free effects and created beings are what the ready mechanics do not cover: note them with the words used."""
    source = await ctx.session.get(Message, action.source_message_id)
    for op in action.operations:
        if op.kind == "free_effect" or (op.kind == "create_object" and op.template == "creature"):
            await record_journal(
                ctx.session,
                ctx.campaign_id,
                "free_effect" if op.kind == "free_effect" else "creature",
                action.source_message_id,
                source.content if source is not None else "",
                {"label": op.label, "scale": op.scale, "abilities": op.abilities, "appearance": op.appearance},
            )
