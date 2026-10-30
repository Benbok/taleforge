"""Shared current-room illustrations, independent of gameplay state and hidden world facts."""

import asyncio
import hashlib
import json
import time
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.agents.portraits import PortraitError, validate_image
from app.core.campaigns import AccessDenied, Conflict, NotFound
from app.core.universal.places import public_location_name
from app.core.universal.scene import universal_scene
from app.db.models import Entity, LlmCall, LocationArtwork, as_utc, new_id, now


def public_source(campaign, location):
    return {
        "identity": public_location_name(campaign, location),
        "appearance": location.description or "",
        "personality": "",
    }


def digest(source):
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def current_location(session, viewer, location_id):
    # Use the same projection as the game, including split parties and undiscovered places.
    visible = await universal_scene(session, viewer.campaign, viewer)
    if (visible.get("location") or {}).get("id") != location_id:
        raise NotFound("локация недоступна")
    location = await session.get(Entity, location_id)
    if not location or location.campaign_id != viewer.campaign.id or location.kind != "location":
        raise NotFound("локация недоступна")
    return location


async def status(session, viewer, location, enabled):
    rows = list(
        await session.scalars(
            select(LocationArtwork)
            .where(LocationArtwork.location_id == location.id)
            .order_by(LocationArtwork.created_at.desc(), LocationArtwork.id.desc())
        )
    )
    latest = rows[0] if rows else None
    ready = next((row for row in rows if row.status == "ready"), None)
    state = latest.status if latest else "idle"
    if latest and state == "pending" and as_utc(latest.lease_until) < now():
        state = "failed"
    return {
        "status": state,
        "image_url": (
            f"/api/campaigns/{viewer.campaign.id}/locations/{location.id}/artwork/{ready.id}" if ready else None
        ),
        "stale": bool(ready and ready.source_digest != digest(public_source(viewer.campaign, location))),
        "enabled": enabled,
        "can_generate": bool(enabled and viewer.can_control_session and (location.description or "").strip()),
        "error": "Не удалось создать иллюстрацию. Можно попробовать ещё раз." if state == "failed" else None,
    }


async def generate(session, viewer, location, request_key, regenerate, generator, translator, media_dir):
    if not viewer.can_control_session:
        raise AccessDenied("иллюстрацию создаёт владелец или мастер")
    if generator is None:
        raise Conflict("генерация иллюстраций локаций не настроена")
    source = public_source(viewer.campaign, location)
    if not source["appearance"].strip():
        raise Conflict("сначала дождитесь описания локации")
    receipt = await session.scalar(
        select(LocationArtwork).where(
            LocationArtwork.campaign_id == viewer.campaign.id,
            LocationArtwork.request_key == request_key,
        )
    )
    if receipt:
        if receipt.location_id != location.id:
            raise Conflict("этот запрос уже использован")
        if receipt.status == "ready":
            return await status(session, viewer, location, True)
        if receipt.status == "failed" or as_utc(receipt.lease_until) < now():
            raise Conflict("предыдущая попытка не завершена; начните новую попытку")
        raise ArtworkPending()
    current = await status(session, viewer, location, True)
    if current["image_url"] and not regenerate:
        return current
    await session.execute(
        update(LocationArtwork)
        .where(
            LocationArtwork.location_id == location.id,
            LocationArtwork.status == "pending",
            LocationArtwork.lease_until < now(),
        )
        .values(status="failed", error="expired")
        .execution_options(synchronize_session="fetch")
    )
    await session.commit()
    seconds = getattr(generator, "timeout_seconds", 600)
    lease_seconds = seconds + 2 * getattr(translator, "timeout_seconds", 20) + 90
    job = LocationArtwork(
        id=new_id("la"),
        campaign_id=viewer.campaign.id,
        location_id=location.id,
        request_key=request_key,
        source_digest=digest(source),
        status="pending",
        lease_until=now() + timedelta(seconds=lease_seconds),
    )
    audit = LlmCall(
        campaign_id=viewer.campaign.id,
        purpose="location_illustration",
        model=generator.model,
        error="interrupted",
        cost_known=False,
    )
    session.add_all([job, audit])
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ArtworkPending() from exc
    # Another request may have completed between the initial cache read and our claim.
    if not regenerate:
        cached = await status(session, viewer, location, True)
        if cached["image_url"]:
            await session.delete(job)
            await session.delete(audit)
            await session.commit()
            return await status(session, viewer, location, True)
    path = media_dir / "locations" / job.id
    reply = None
    started = time.monotonic()
    try:
        # Known exits go to the prompt only; the cache digest stays the public description alone.
        from app.core.map_backdrop import visible_passages

        passages = await visible_passages(session, viewer)
        described = source
        if passages:
            names = "; ".join(f"«{p['name']}»" for p in passages)
            described = {**source, "appearance": f"{source['appearance']}\n\nВыходы из места: {names}."}
        prepared = await translator.translate(session, described, viewer.campaign.id) if translator else described
        async with asyncio.timeout(seconds + 10):
            reply = await generator.generate(prepared)
        validate_image(reply.data, reply.mime)
        await session.refresh(location)
        if digest(public_source(viewer.campaign, location)) != job.source_digest:
            raise PortraitError("stale_location")
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, reply.data)
        changed = await session.execute(
            update(LocationArtwork)
            .where(
                LocationArtwork.id == job.id,
                LocationArtwork.status == "pending",
                LocationArtwork.lease_until >= now(),
            )
            .values(status="ready", mime=reply.mime, error=None)
            .execution_options(synchronize_session="fetch")
        )
        if changed.rowcount != 1:
            raise PortraitError("expired")
        audit.error = None
    except Exception as exc:
        reason = str(exc) if isinstance(exc, PortraitError) else "generation_error"
        await session.execute(
            update(LocationArtwork)
            .where(
                LocationArtwork.id == job.id,
                LocationArtwork.status == "pending",
            )
            .values(status="failed", error=reason[:64])
        )
        await asyncio.to_thread(path.unlink, missing_ok=True)
        audit.error = reason
    if reply:
        audit.model = reply.model
        audit.tokens_in, audit.tokens_out = reply.tokens_in, reply.tokens_out
        audit.tokens_reasoning = reply.tokens_reasoning
        audit.cost, audit.cost_known = reply.cost, reply.cost_known
    audit.latency_ms = int((time.monotonic() - started) * 1000)
    await session.commit()
    if audit.error:
        message = (
            "Описание места изменилось. Попробуйте создать иллюстрацию ещё раз."
            if audit.error == "stale_location"
            else ("Не удалось создать иллюстрацию. Прежняя картинка сохранена; проверьте ComfyUI и попробуйте ещё раз.")
        )
        raise Conflict(message)
    return await status(session, viewer, location, True)


class ArtworkPending(Conflict):
    def __init__(self):
        super().__init__("Иллюстрация уже создаётся. Дождитесь результата.")


async def read_image(session, viewer, location, image_id, media_dir):
    image = await session.get(LocationArtwork, image_id)
    if (
        not image
        or image.location_id != location.id
        or image.campaign_id != viewer.campaign.id
        or image.status != "ready"
    ):
        raise NotFound("иллюстрация не найдена")
    path = media_dir / "locations" / image.id
    if not path.is_file():
        raise NotFound("файл иллюстрации не найден")
    return path, image.mime
