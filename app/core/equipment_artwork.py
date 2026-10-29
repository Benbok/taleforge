"""Explicit, reusable item artwork, with no inventory or game-state mutations."""

import asyncio
import hashlib
import io
import json
import time
from datetime import timedelta

from PIL import Image
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.agents.portraits import PortraitError, validate_image
from app.core.campaigns import AccessDenied, Conflict, NotFound
from app.core.characters import get_character
from app.core.equipment_artwork_scope import ArtworkScope, as_scope
from app.core.universal.inventory import item_view, starter_views, state_of
from app.core.universal.profiles import load_actor
from app.db.models import Entity, EquipmentArtwork, LlmCall, as_utc, new_id, now


async def available_item(session, viewer, hero_id, item_id):
    hero = await get_character(session, viewer, hero_id)
    await session.refresh(hero)
    if not viewer.is_master and (not viewer.seat or viewer.seat.id != hero.seat_id):
        raise AccessDenied("Снаряжение доступно игроку этого героя и мастеру")
    if hero.sheet.get("rules_version") != "universal.v1":
        raise NotFound("Предмет недоступен")
    # Starter views deliberately exist before inventory is materialized by a gameplay action.
    if not hero.resources.get("inventory_initialized"):
        sheet, _ = await load_actor(session, viewer.campaign.id, hero.id)
        for item in starter_views(viewer.campaign.id, hero.id, sheet):
            if item["id"] == item_id:
                return item
    row = await session.get(Entity, item_id, populate_existing=True)
    if (
        not row
        or row.campaign_id != viewer.campaign.id
        or row.kind != "object"
        or "universal_item" not in row.state
        or row.state.get("hidden")
    ):
        raise NotFound("Предмет недоступен")
    state = state_of(row)
    if state.owner_id != hero.id or state.quantity < 1:
        raise NotFound("Предмет недоступен")
    return item_view(row)


def public_source(item):
    kinds = {"weapon": "weapon", "armor": "standalone armor", "consumable": "consumable item"}
    return {
        "identity": item["name"],
        "appearance": item.get("description", ""),
        "personality": kinds[item["kind"]],
    }


def digest(source):
    return hashlib.sha256(json.dumps(["equipment-v1", source], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def status(session, campaign_id, source, base, enabled):
    scope = as_scope(campaign_id)
    rows = list(
        await session.scalars(
            select(EquipmentArtwork)
            .where(
                scope.read_filter(),
                EquipmentArtwork.source_digest == digest(source),
            )
            .order_by(EquipmentArtwork.created_at.desc(), EquipmentArtwork.id.desc())
        )
    )
    ready = max(
        (r for r in rows if r.status == "ready"),
        default=None,
        key=lambda r: (as_utc(r.selected_at or r.created_at), as_utc(r.created_at), r.id),
    )
    latest = rows[0] if rows else None
    unfinished = next((r for r in rows if r.status != "ready"), None)
    if ready:
        latest = (
            unfinished
            if unfinished and as_utc(unfinished.created_at) > as_utc(ready.selected_at or ready.created_at)
            else ready
        )
    state = latest.status if latest else "idle"
    if latest and state == "pending" and as_utc(latest.lease_until) < now():
        state = "failed"
    image_id = (ready.reused_from or ready.id) if ready else None
    return dict(
        status=state,
        image_url=f"{base}/{image_id}" if ready else None,
        thumbnail_url=f"{base}/{image_id}/thumbnail" if ready else None,
        enabled=enabled,
        can_generate=bool(enabled and not ready),
        error="Не удалось создать изображение предмета. Можно повторить попытку." if state == "failed" else None,
    )


def thumbnail(data, mime):
    validate_image(data, mime)
    try:
        with Image.open(io.BytesIO(data), formats=("PNG", "JPEG", "WEBP")) as image:
            if image.width * image.height > 4_194_304 or Image.MIME[image.format] != mime:
                raise ValueError("invalid size or type")
            image.load()
            image.thumbnail((256, 256), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.convert("RGBA" if "A" in image.getbands() else "RGB").save(output, "WEBP", quality=82)
            return output.getvalue()
    except Exception as exc:
        raise PortraitError("invalid_image") from exc


class ArtworkPending(Conflict):
    def __init__(self):
        super().__init__("Изображение уже создаётся. Дождитесь результата.")


async def save_cached(session, scope, source, base, key, cached, media_dir, job=None):
    image_id = cached["image_url"].rsplit("/", 1)[-1]
    original = await session.get(EquipmentArtwork, image_id)
    row = job or EquipmentArtwork(
        id=new_id("ea"), **scope.values, request_key=key, source_digest=digest(source), lease_until=now()
    )
    row.status = "ready"
    row.reused_from = image_id
    row.selected_at = original.selected_at or original.created_at
    copied = []
    # Library artwork must survive deletion of the campaign that originally generated it.
    if scope.campaign_id is None and original.campaign_id is not None:
        row.reused_from = None
        row.mime = original.mime
        for suffix in ("", ".webp"):
            destination = media_dir / "equipment" / (row.id + suffix)
            destination.write_bytes((media_dir / "equipment" / (image_id + suffix)).read_bytes())
            copied.append(destination)
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        for path in copied:
            path.unlink(missing_ok=True)
        previous = await session.scalar(
            select(EquipmentArtwork).where(
                scope.own_filter(),
                EquipmentArtwork.request_key == key,
            )
        )
        if not previous or previous.source_digest != digest(source) or previous.regenerate:
            raise Conflict("Этот запрос уже использован для другого предмета") from None
        if previous.status != "ready":
            raise ArtworkPending() from None
    return await status(session, scope, source, base, True)


async def generate(
    session, viewer, hero_id, item_id, source, base, key, generator, translator, media_dir, scope=None, regenerate=False
):
    if scope is None:
        scope = ArtworkScope(viewer.campaign.id)

    async def resolve_current():
        return await available_item(session, viewer, hero_id, item_id)

    return await generate_scoped(
        session, scope, source, base, key, generator, translator, media_dir, resolve_current, regenerate=regenerate
    )


async def generate_scoped(
    session, scope, source, base, key, generator, translator, media_dir, resolve_current, regenerate=False
):
    if generator is None:
        raise Conflict("Генерация изображений снаряжения не настроена")
    source_digest = digest(source)
    receipt = await session.scalar(
        select(EquipmentArtwork).where(
            scope.own_filter(),
            EquipmentArtwork.request_key == key,
        )
    )
    if receipt:
        if receipt.source_digest != source_digest or receipt.regenerate != regenerate:
            raise Conflict("Этот запрос уже использован для другого предмета")
        if receipt.status == "ready":
            return await status(session, scope, source, base, True)
        if receipt.status == "failed" or as_utc(receipt.lease_until) < now():
            raise Conflict("Начните новую попытку создания изображения")
        raise ArtworkPending()
    cached = await status(session, scope, source, base, True)
    if cached["image_url"] and not regenerate:
        return await save_cached(session, scope, source, base, key, cached, media_dir)
    await session.execute(
        update(EquipmentArtwork)
        .where(
            or_(EquipmentArtwork.pending_scope == scope.values["pending_scope"], scope.own_filter()),
            EquipmentArtwork.source_digest == source_digest,
            EquipmentArtwork.status == "pending",
            EquipmentArtwork.lease_until < now(),
        )
        .values(status="failed", error="expired")
        .execution_options(synchronize_session="fetch")
    )
    await session.commit()
    seconds = getattr(generator, "timeout_seconds", 600)
    job = EquipmentArtwork(
        id=new_id("ea"),
        **scope.values,
        request_key=key,
        source_digest=source_digest,
        status="pending",
        regenerate=regenerate,
        lease_until=now() + timedelta(seconds=seconds + 2 * getattr(translator, "timeout_seconds", 20) + 90),
    )
    audit = LlmCall(
        campaign_id=scope.campaign_id,
        purpose="equipment_illustration",
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
    # Close the gap between the first cache read and claiming a completed predecessor's slot.
    cached = await status(session, scope, source, base, True)
    if cached["image_url"] and not regenerate:
        await session.delete(audit)
        return await save_cached(session, scope, source, base, key, cached, media_dir, job=job)
    original = media_dir / "equipment" / job.id
    small = original.with_suffix(".webp")
    reply = None
    cancelled = None
    started = time.monotonic()
    try:
        prepared = await translator.translate(session, source, scope.campaign_id) if translator else source
        async with asyncio.timeout(seconds + 10):
            reply = await generator.generate({**prepared, "item_kind": source["personality"]})
        preview = await asyncio.to_thread(thumbnail, reply.data, reply.mime)
        current = await resolve_current()
        if digest(public_source(current)) != source_digest:
            raise PortraitError("stale_item")
        # Small bounded local writes; no cancellable background writes may outlive cleanup.
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(reply.data)
        small.write_bytes(preview)
        changed = await session.execute(
            update(EquipmentArtwork)
            .where(
                EquipmentArtwork.id == job.id,
                EquipmentArtwork.status == "pending",
                EquipmentArtwork.lease_until >= now(),
            )
            .values(status="ready", mime=reply.mime, error=None, selected_at=now())
            .execution_options(synchronize_session="fetch")
        )
        if changed.rowcount != 1:
            raise PortraitError("expired")
        audit.error = None
    except (Exception, asyncio.CancelledError) as exc:
        cancelled = exc if isinstance(exc, asyncio.CancelledError) else None
        reason = str(exc) if isinstance(exc, PortraitError) else "generation_error"
        await session.execute(
            update(EquipmentArtwork)
            .where(
                EquipmentArtwork.id == job.id,
                EquipmentArtwork.status == "pending",
            )
            .values(status="failed", error=reason[:64])
        )
        original.unlink(missing_ok=True)
        small.unlink(missing_ok=True)
        audit.error = reason
    if reply:
        audit.model = reply.model
        audit.tokens_in, audit.tokens_out = reply.tokens_in, reply.tokens_out
        audit.tokens_reasoning = reply.tokens_reasoning
        audit.cost, audit.cost_known = reply.cost, reply.cost_known
    audit.latency_ms = int((time.monotonic() - started) * 1000)
    await session.commit()
    if cancelled:
        raise cancelled
    if audit.error:
        raise Conflict("Не удалось создать изображение предмета. Проверьте ComfyUI и повторите попытку.")
    return await status(session, scope, source, base, True)


async def read_image(session, campaign_id, source, image_id, media_dir, small=False):
    scope = as_scope(campaign_id)
    row = await session.get(EquipmentArtwork, image_id)
    if not row or row.source_digest != digest(source) or row.status != "ready":
        raise NotFound("Изображение недоступно")
    if not scope.permits(row):
        adopted = await session.scalar(
            select(EquipmentArtwork.id).where(
                scope.own_filter(),
                EquipmentArtwork.reused_from == image_id,
                EquipmentArtwork.source_digest == digest(source),
                EquipmentArtwork.status == "ready",
            )
        )
        if not adopted:
            raise NotFound("Изображение недоступно")
    path = media_dir / "equipment" / row.id
    if small:
        path = path.with_suffix(".webp")
    if not path.is_file():
        raise NotFound("Файл изображения не найден")
    return path, "image/webp" if small else row.mime
