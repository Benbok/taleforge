"""Protected portrait candidates from encountered NPC projections; selection is always explicit."""

import asyncio
import hashlib
import json
import time
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.agents.portraits import PortraitError
from app.core.campaigns import AccessDenied, Conflict, NotFound, is_admin
from app.core.equipment_artwork import thumbnail
from app.core.inspect import InspectError, entity_card, viewer_hero
from app.core.universal.scene import universal_scene
from app.db.models import Character, Entity, Knowledge, LlmCall, NpcPortrait, NpcPortraitSelection, as_utc, new_id, now


def manages(viewer):
    return viewer.can_control_session or is_admin(viewer.user)


async def source_for(session, viewer, npc_id):
    npc = await session.get(Entity, npc_id, populate_existing=True)
    if not npc or npc.campaign_id != viewer.campaign.id or npc.kind != "creature":
        raise NotFound("Персонаж недоступен")
    try:
        card = await entity_card(session, viewer, npc_id)
    except InspectError as exc:
        raise NotFound("Персонаж недоступен") from exc
    name, appearance = card["name"], card.get("description") or ""
    if not viewer.is_master:
        scene = await universal_scene(session, viewer.campaign, viewer)
        if npc_id not in {row["id"] for row in scene.get("entities", [])}:
            hero = await viewer_hero(session, viewer)
            knowledge = await session.get(Knowledge, (hero.id, npc_id)) if hero else None
            observed = (knowledge.observed_snapshot or {}) if knowledge else {}
            name, appearance = observed.get("name") or "Знакомый персонаж", observed.get("description") or ""
    return {"identity": name, "appearance": appearance, "personality": ""}


def digest(source):
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def remember_encounter(session, cid, npc_id, source):
    from app.core.object_policy import remember_visible
    from app.core.world import PLAYABLE, get_scene

    npc = await session.get(Entity, npc_id)
    if npc is None or not npc.location_id:
        return
    if source["appearance"] != npc.description or source["identity"] != npc.name:
        return  # A portrait from memory must never record the NPC's unobserved current look.
    entities = {e.id: e for e in await session.scalars(select(Entity).where(Entity.campaign_id == cid))}
    scene = await get_scene(session, cid)
    heroes = [
        h
        for h in await session.scalars(select(Character).where(Character.campaign_id == cid))
        if h.status in PLAYABLE and (h.location_id or scene.location_id) == npc.location_id
    ]
    if npc.state.get("visibility") in {"hidden", "private"}:
        return
    try:
        async with session.begin_nested():
            await remember_visible(session, entities, heroes, [npc], [])
    except IntegrityError:
        pass  # A simultaneous normal scene observation already recorded this encounter.
    await session.commit()


async def status(session, viewer, npc_id, source, enabled):
    rows = list(
        await session.scalars(
            select(NpcPortrait)
            .where(
                NpcPortrait.npc_id == npc_id,
                NpcPortrait.source_digest == digest(source),
            )
            .order_by(NpcPortrait.created_at.desc(), NpcPortrait.id.desc())
        )
    )
    selection = await session.get(NpcPortraitSelection, (npc_id, digest(source)))
    selected = selection.image_id if selection else None
    if selection and selection.chosen_at:
        cutoff = as_utc(selection.chosen_at)
        rows = [
            row
            for row in rows
            if row.id == selected
            or as_utc(row.created_at) > cutoff
            or (row.status == "pending" and as_utc(row.lease_until) >= now())
        ]
    ready = [row for row in rows if row.status == "ready"]
    shown = ready[:12]
    if selected and all(row.id != selected for row in shown):
        shown += [row for row in ready if row.id == selected]
    base = f"/api/campaigns/{viewer.campaign.id}/npcs/{npc_id}/portraits"
    latest = rows[0] if rows else None
    state = latest.status if latest else "idle"
    if latest and state == "pending" and as_utc(latest.lease_until) < now():
        state = "failed"
    return dict(
        status=state,
        selected_id=selected,
        enabled=enabled,
        can_generate=bool(enabled and manages(viewer) and source["appearance"].strip()),
        can_select=manages(viewer),
        variants=[
            dict(id=row.id, image_url=f"{base}/{row.id}", thumbnail_url=f"{base}/{row.id}/thumbnail") for row in shown
        ],
        error="Не удалось создать вариант портрета. Выбранный портрет сохранён." if state == "failed" else None,
    )


class PortraitPending(Conflict):
    pass


async def generate(session, viewer, npc_id, source, key, generator, translator, media_dir):
    if not manages(viewer):
        raise AccessDenied("Портретами NPC управляет владелец или мастер")
    if generator is None or not source["appearance"].strip():
        raise Conflict("Для портрета нужны доступное описание и настроенная генерация")
    cid, source_digest = viewer.campaign.id, digest(source)
    receipt = await session.scalar(
        select(NpcPortrait).where(NpcPortrait.campaign_id == cid, NpcPortrait.request_key == key)
    )
    if receipt:
        if receipt.npc_id != npc_id or receipt.source_digest != source_digest:
            raise Conflict("Этот запрос уже использован")
        if receipt.status == "ready":
            return await status(session, viewer, npc_id, source, True)
        if receipt.status == "pending" and as_utc(receipt.lease_until) >= now():
            raise PortraitPending("Портрет уже создаётся")
        raise Conflict("Начните новую попытку создания варианта")
    await session.execute(
        update(NpcPortrait)
        .where(
            NpcPortrait.npc_id == npc_id,
            NpcPortrait.status == "pending",
            NpcPortrait.lease_until < now(),
        )
        .values(status="failed", error="expired")
    )
    await session.commit()
    seconds = getattr(generator, "timeout_seconds", 600)
    job_id = new_id("np")
    job = NpcPortrait(
        id=job_id,
        campaign_id=cid,
        npc_id=npc_id,
        request_key=key,
        source_digest=source_digest,
        status="pending",
        lease_until=now() + timedelta(seconds=seconds + 2 * getattr(translator, "timeout_seconds", 20) + 90),
    )
    audit = LlmCall(
        campaign_id=cid, purpose="npc_portrait", model=generator.model, error="interrupted", cost_known=False
    )
    session.add_all([job, audit])
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise PortraitPending("Портрет уже создаётся") from exc
    path = media_dir / "npcs" / job_id
    small = path.with_suffix(".webp")
    started, reply, cancelled = time.monotonic(), None, None
    try:
        await remember_encounter(session, cid, npc_id, source)
        prepared = await translator.translate(session, source, cid) if translator else source
        async with asyncio.timeout(seconds + 10):
            reply = await generator.generate(prepared)
        preview = await asyncio.to_thread(thumbnail, reply.data, reply.mime)
        if digest(await source_for(session, viewer, npc_id)) != source_digest:
            raise PortraitError("stale_npc")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(reply.data)
        small.write_bytes(preview)
        changed = await session.execute(
            update(NpcPortrait)
            .where(
                NpcPortrait.id == job_id,
                NpcPortrait.status == "pending",
                NpcPortrait.lease_until >= now(),
            )
            .values(status="ready", mime=reply.mime, error=None)
            .execution_options(synchronize_session="fetch")
        )
        if changed.rowcount != 1:
            raise PortraitError("expired")
        audit.error = None
    except (Exception, asyncio.CancelledError) as exc:
        cancelled = exc if isinstance(exc, asyncio.CancelledError) else None
        reason = str(exc) if isinstance(exc, PortraitError) else "generation_error"
        await session.execute(
            update(NpcPortrait)
            .where(NpcPortrait.id == job_id, NpcPortrait.status == "pending")
            .values(status="failed", error=reason[:64])
        )
        path.unlink(missing_ok=True)
        small.unlink(missing_ok=True)
        audit.error = reason
    if reply:
        audit.model, audit.tokens_in, audit.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
        audit.tokens_reasoning, audit.cost, audit.cost_known = reply.tokens_reasoning, reply.cost, reply.cost_known
    audit.latency_ms = int((time.monotonic() - started) * 1000)
    await session.commit()
    if cancelled:
        raise cancelled
    if audit.error:
        raise Conflict("Не удалось создать вариант портрета. Прежний выбор сохранён.")
    return await status(session, viewer, npc_id, source, True)


async def candidate(session, viewer, npc_id, source, image_id):
    row = await session.get(NpcPortrait, image_id)
    if (
        not row
        or row.campaign_id != viewer.campaign.id
        or row.npc_id != npc_id
        or row.source_digest != digest(source)
        or row.status != "ready"
    ):
        raise NotFound("Вариант портрета недоступен")
    return row


async def apply(session, viewer, npc_id, source, image_id, enabled):
    if not manages(viewer):
        raise AccessDenied("Портрет выбирает владелец или мастер")
    await candidate(session, viewer, npc_id, source, image_id)
    key = (npc_id, digest(source))
    selection = await session.get(NpcPortraitSelection, key)
    if selection:
        selection.image_id = image_id
        selection.chosen_at = now()
    else:
        session.add(NpcPortraitSelection(npc_id=npc_id, source_digest=key[1], image_id=image_id, chosen_at=now()))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        selection = await session.get(NpcPortraitSelection, key)
        if not selection:
            raise Conflict("Повторите выбор портрета") from None
        selection.image_id = image_id
        selection.chosen_at = now()
        await session.commit()
        # Refresh authentication projection after rollback expired ORM instances.
        await session.refresh(viewer.campaign)
        await session.refresh(viewer.user)
        if viewer.seat:
            await session.refresh(viewer.seat)
    return await status(session, viewer, npc_id, source, enabled)
