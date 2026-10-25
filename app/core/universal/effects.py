"""Persistent bounded effects. Reads do not tick, expiration is transaction-owned."""

from sqlalchemy import select

from app.core.campaigns import AccessDenied, Conflict
from app.db.models import Character, Entity, Event, UniversalEffect
from app.rules.universal.exploration import EffectChange, EffectIntentV2

RENEWABLE_KINDS = frozenset({"change_form", "camouflage", "illumination"})


async def start_effect(
    session,
    campaign_id,
    actor_id,
    target_id,
    event_id,
    component,
    spec,
    starts_seconds,
    duration_seconds,
    *,
    context=None,
):
    spec = EffectIntentV2.model_validate(spec.model_dump())
    if (
        type(starts_seconds) is not int
        or starts_seconds < 0
        or type(duration_seconds) is not int
        or duration_seconds < 1
    ):
        raise ValueError("Invalid effect time")
    actor = await session.get(Character, actor_id)
    target = await session.get(Character, target_id) or await session.get(Entity, target_id)
    event = await session.get(Event, event_id)
    if (
        actor is None
        or actor.campaign_id != campaign_id
        or target is None
        or target.campaign_id != campaign_id
        or event is None
        or event.campaign_id != campaign_id
        or event.actor_id != actor_id
    ):
        raise AccessDenied("Effect scope mismatch")
    data = {**spec.model_dump(mode="json"), "context": context or {}}
    previous = await session.scalar(
        select(UniversalEffect).where(
            UniversalEffect.campaign_id == campaign_id,
            UniversalEffect.source_event_id == event_id,
            UniversalEffect.target_id == target_id,
            UniversalEffect.component == component,
        )
    )
    if previous is not None:
        if previous.definition != data:
            raise Conflict("Saved effect changed")
        return previous
    effect = UniversalEffect(
        campaign_id=campaign_id,
        source_actor_id=actor_id,
        source_event_id=event_id,
        target_id=target_id,
        component=component,
        definition=data,
        starts_seconds=str(starts_seconds),
        ends_seconds=str(starts_seconds + duration_seconds),
        status="active",
    )
    session.add(effect)
    await session.flush()
    if spec.kind in RENEWABLE_KINDS:
        # Casting the same effect again renews it: the earlier one ends exactly where the new one begins.
        earlier = await session.scalars(
            select(UniversalEffect).where(
                UniversalEffect.campaign_id == campaign_id,
                UniversalEffect.target_id == target_id,
                UniversalEffect.status == "active",
                UniversalEffect.id != effect.id,
            )
        )
        for row in earlier:
            if row.definition["kind"] == spec.kind and int(row.ends_seconds) > starts_seconds:
                row.ends_seconds = str(max(starts_seconds, int(row.starts_seconds)))
        await session.flush()
    return effect


async def active_effects(session, campaign_id, target_id=None, *, at_seconds=None):
    if at_seconds is None:
        from app.core.universal.clock import clock_view

        at_seconds = int((await clock_view(session, campaign_id))["game_seconds"])
    query = select(UniversalEffect).where(
        UniversalEffect.campaign_id == campaign_id, UniversalEffect.status == "active"
    )
    if target_id is not None:
        query = query.where(UniversalEffect.target_id == target_id)
    rows = await session.scalars(query.order_by(UniversalEffect.id))
    return [
        dict(
            id=row.id,
            source_actor_id=row.source_actor_id,
            source_event_id=row.source_event_id,
            target_id=row.target_id,
            kind=row.definition["kind"],
            definition=row.definition,
            remaining_seconds=str(int(row.ends_seconds) - at_seconds),
        )
        for row in rows
        if int(row.starts_seconds) <= at_seconds < int(row.ends_seconds)
    ]


async def _end(session, row, status):
    row.status = status
    changes = [
        EffectChange(
            kind="effect_ended",
            subject_id=row.target_id,
            description=f"Эффект «{row.definition.get('label') or row.definition['kind']}» завершён.",
            data=dict(effect_id=row.id, effect_kind=row.definition["kind"]),
        )
    ]
    if row.definition["kind"] == "create_object":
        from app.core.universal.objects import expire_temporary_object

        changes.extend(await expire_temporary_object(session, row.campaign_id, row.target_id))
    return changes


async def expire_effects(session, campaign_id, game_seconds):
    rows = list(
        await session.scalars(
            select(UniversalEffect).where(
                UniversalEffect.campaign_id == campaign_id, UniversalEffect.status == "active"
            )
        )
    )
    changes = []
    for row in rows:
        if int(row.ends_seconds) <= game_seconds:
            changes.extend(await _end(session, row, "expired"))
    # A camouflage component dependent on a form cannot outlive dismissal of that form.
    for row in rows:
        if row.status != "active" or not row.definition.get("context", {}).get("requires_form"):
            continue
        if not any(
            other.status == "active"
            and other.source_event_id == row.source_event_id
            and other.target_id == row.target_id
            and other.definition["kind"] == "change_form"
            for other in rows
        ):
            changes.extend(await _end(session, row, "dismissed"))
    await session.flush()
    return changes


async def dismiss_effect(session, campaign_id, actor_id, effect_id):
    row = await session.get(UniversalEffect, effect_id, populate_existing=True)
    if row is None or row.campaign_id != campaign_id or row.source_actor_id != actor_id:
        raise AccessDenied("Only the effect source may dismiss it")
    if row.status != "active":
        return []
    changes = await _end(session, row, "dismissed")
    from app.core.universal.clock import clock_view

    changes.extend(
        await expire_effects(session, campaign_id, int((await clock_view(session, campaign_id))["game_seconds"]))
    )
    return changes
