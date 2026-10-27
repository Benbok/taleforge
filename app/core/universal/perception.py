"""Noncombat perception from saved observers/effects; no narrative-only hidden status."""

import hashlib

from sqlalchemy import select

from app.core.campaigns import AccessDenied
from app.core.universal.effects import active_effects
from app.core.universal.profiles import load_actor
from app.db.models import Character, Entity, Event, KnownFact, Message
from app.rules.universal.exploration import EffectChange
from app.rules.universal.profiles import resolve_check


async def established_evidence(session, campaign_id, actor_id):
    actor = await session.get(Character, actor_id)
    if actor is None or actor.campaign_id != campaign_id:
        raise AccessDenied("Неверная область героя")
    location = await session.get(Entity, actor.location_id) if actor.location_id else None
    parts = [location.description] if location and location.campaign_id == campaign_id else []
    for message in await session.scalars(
        select(Message)
        .where(Message.campaign_id == campaign_id, Message.kind == "narration")
        .order_by(Message.seq.desc())
        .limit(20)
    ):
        data = message.data or {}
        if data.get("whisper_reply") or data.get("scope") == "private":
            continue
        if message.visible_to is not None and (actor.seat_id not in message.visible_to or data.get("scope") != "party"):
            continue
        place = data.get("location_id") or (data.get("location_ref") or {}).get("id")
        if actor.location_id is not None and place == actor.location_id:
            parts.append(message.content)
    return "\n".join(parts)


def observer_id(campaign_id, location_id, spec):
    return (
        "en_" + hashlib.sha256(f"{campaign_id}:{location_id}:observer:{spec.evidence_quote}".encode()).hexdigest()[:24]
    )


async def introduce_observer(ctx, spec):
    actor = await ctx.session.get(Character, ctx.actor_id)
    if spec.evidence_quote not in await established_evidence(ctx.session, ctx.campaign_id, ctx.actor_id):
        raise ValueError("Нет известного основания для наблюдателя")
    key = observer_id(ctx.campaign_id, actor.location_id, spec)
    row = await ctx.session.get(Entity, key)
    if row is None:
        row = Entity(
            id=key,
            campaign_id=ctx.campaign_id,
            kind="creature",
            name=spec.name,
            description=spec.evidence_quote,
            location_id=actor.location_id,
            state={
                "exploration_observer": {
                    "wis": "10",
                    "notices": {actor.id: "witness"} if spec.awareness == "watching_actor" else {},
                },
                "cover_available": False,
            },
        )
        ctx.session.add(row)
        await ctx.session.flush()
    return row


async def actor_constraints(session, campaign_id, actor_id):
    form = any(e["kind"] == "change_form" for e in await active_effects(session, campaign_id, actor_id))
    return dict(
        form="plant_bush" if form else None,
        can_move=not form,
        can_speak=not form,
        can_manipulate=not form,
        can_see=True,
        can_hear=True,
        needs_air=True,
        immune=False,
        can_dismiss=True,
    )


def stealth_edge(effects, context):
    return (
        "advantage"
        if (
            context.get("cover")
            and not context.get("direct_witness")
            and any(e["kind"] == "camouflage" for e in effects)
        )
        else "normal"
    )


async def illumination_view(session, campaign_id, actor_id):
    actor = await session.get(Character, actor_id)
    if actor is None or actor.campaign_id != campaign_id:
        raise AccessDenied("Неверная область света")
    holders = {
        h.id
        for h in await session.scalars(
            select(Character).where(Character.campaign_id == campaign_id, Character.location_id == actor.location_id)
        )
    }
    light = any(
        e["kind"] == "illumination" and e["target_id"] in holders for e in await active_effects(session, campaign_id)
    )
    return dict(magical_light=light, reveals_secrets=False)


async def assess_detection(ctx, observer_id, actor_id, source_key, *, at_seconds=None):
    s = ctx.session
    actor = await s.get(Character, actor_id)
    observer = await s.get(Entity, observer_id)
    if (
        actor is None
        or actor.id != ctx.actor_id
        or actor.campaign_id != ctx.campaign_id
        or observer is None
        or observer.campaign_id != ctx.campaign_id
        or observer.location_id != actor.location_id
        or "exploration_observer" not in observer.state
    ):
        raise AccessDenied("Наблюдатель недоступен")
    key = "detect-" + hashlib.sha256(f"{source_key}:{observer.id}:{actor_id}".encode()).hexdigest()[:40]
    previous = await s.scalar(select(Event).where(Event.campaign_id == ctx.campaign_id, Event.idempotency_key == key))
    if previous:
        return EffectChange.model_validate(previous.payload["change"])
    state = observer.state["exploration_observer"]
    witness = state.get("notices", {}).get(actor_id) in {"witness", "detected"}
    effects = await active_effects(s, ctx.campaign_id, actor_id, at_seconds=at_seconds)
    edge = stealth_edge(
        effects,
        dict(
            cover=observer.state.get("cover_available", False) or any(e["kind"] == "change_form" for e in effects),
            direct_witness=witness,
        ),
    )
    sheet, _ = await load_actor(s, ctx.campaign_id, actor_id)
    difficulty = 10 + (int(state["wis"]) - 10) // 2
    cover = observer.state.get("cover_available", False) or any(e["kind"] == "change_form" for e in effects)
    check = resolve_check(ctx.dice, sheet.abilities.dex, False, difficulty, edge) if cover and not witness else None
    concealed = bool(check and check.success)
    observer.state = {
        **observer.state,
        "exploration_observer": {
            **state,
            "notices": {
                **state.get("notices", {}),
                actor_id: "witness" if witness else "concealed" if concealed else "detected",
            },
        },
    }
    from app.core.universal.visibility import visible_entity

    private = not await visible_entity(s, ctx.campaign_id, actor_id, observer)
    change = EffectChange(
        kind="detection",
        subject_id=actor_id,
        private=private,
        description="Свидетель помнит, где находится герой."
        if witness
        else "Герой избежал обнаружения этим наблюдателем."
        if concealed
        else "Наблюдатель замечает героя.",
        data=dict(
            observer_id=observer.id,
            concealed=concealed,
            natural=check.natural if check else None,
            rolls=check.rolls if check else [],
            total=str(check.total) if check else None,
            mode=edge,
            critical=check.critical if check else False,
            critical_failure=check.critical_failure if check else False,
        ),
    )
    s.add(
        Event(
            campaign_id=ctx.campaign_id,
            actor_id=actor_id,
            tool="exploration_detection",
            idempotency_key=key,
            payload=dict(change=change.model_dump(mode="json"), difficulty=str(difficulty)),
        )
    )
    await s.flush()
    return change


async def observe_known_scene(ctx, aspect, target_id=None):
    """Successful observation records only accessible, already established details. A named target narrows it to
    that one; listening with none narrows it to the living things that can be heard."""
    actor = await ctx.session.get(Character, ctx.actor_id)
    changes = []
    if actor.location_id is None:
        return changes
    light = await illumination_view(ctx.session, ctx.campaign_id, actor.id)
    from app.core.universal.visibility import visible_entity

    for row in await ctx.session.scalars(select(Entity).where(Entity.campaign_id == ctx.campaign_id)):
        if row.id != actor.location_id and row.location_id != actor.location_id:
            continue
        if target_id and row.id != target_id:
            continue
        if aspect == "hearing" and not target_id and row.kind != "creature":
            continue
        if row.state.get("hidden") or row.state.get("visibility") in {"hidden", "private"}:
            continue
        if not await visible_entity(ctx.session, ctx.campaign_id, actor.id, row):
            continue
        if "exploration" in row.state and row.state["exploration"].get("owner_id") not in {None, actor.id}:
            continue
        if "exploration" in row.state and (
            row.state["exploration"].get("expired") or int(row.state["exploration"].get("amount", "0")) < 1
        ):
            continue
        if "universal_item" in row.state and (
            row.state["universal_item"].get("owner_id") != actor.id
            or int(row.state["universal_item"].get("quantity", "0")) < 1
        ):
            continue
        if row.state.get("requires_light") and not light["magical_light"]:
            continue
        text = (row.description or row.name)[:300]
        fact = await ctx.session.scalar(
            select(KnownFact).where(
                KnownFact.character_id == actor.id,
                KnownFact.subject_id == row.id,
                KnownFact.text == text,
            )
        )
        if fact is None:
            ctx.session.add(KnownFact(campaign_id=ctx.campaign_id, character_id=actor.id, subject_id=row.id, text=text))
        changes.append(
            EffectChange(
                kind="observation",
                subject_id=row.id,
                description=text,
                data=dict(aspect=aspect, magical_light=light["magical_light"]),
            )
        )
    await ctx.session.flush()
    return changes
