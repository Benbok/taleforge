"""Status, generation and file access for any ArtworkRecipe; same rules as the location illustration."""

import asyncio
import hashlib
import inspect
import json
import time
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.agents.portraits import PortraitError, validate_image
from app.core.artwork.recipe import ArtworkRecipe
from app.core.campaigns import AccessDenied, Conflict, NotFound
from app.db.models import Artwork, LlmCall, as_utc, new_id, now


class ArtworkPending(Conflict):
    def __init__(self, noun="картинку"):
        super().__init__(f"Уже создаётся: {noun}. Дождитесь результата.")


def digest(source) -> str:
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def _source(session, viewer, recipe, subject) -> dict:
    value = recipe.source(viewer, subject, session) if recipe.source_needs_session else recipe.source(viewer, subject)
    return await value if inspect.isawaitable(value) else value


async def _rows(session, viewer, recipe, subject):
    return list(
        await session.scalars(
            select(Artwork)
            .where(
                Artwork.campaign_id == viewer.campaign.id,
                Artwork.kind == recipe.kind,
                Artwork.subject_id == subject.id,
            )
            .order_by(Artwork.created_at.desc(), Artwork.id.desc())
        )
    )


async def status(session, viewer, recipe: ArtworkRecipe, subject, enabled) -> dict:
    rows = await _rows(session, viewer, recipe, subject)
    latest = rows[0] if rows else None
    ready = next((row for row in rows if row.status == "ready"), None)
    state = latest.status if latest else "idle"
    if latest and state == "pending" and as_utc(latest.lease_until) < now():
        state = "failed"
    source = await _source(session, viewer, recipe, subject)
    return {
        "status": state,
        "image_url": recipe.url(viewer.campaign.id, subject.id, ready.id) if ready else None,
        "stale": bool(ready and ready.source_digest != digest(source)),
        "enabled": enabled,
        "can_generate": bool(enabled and recipe.permitted(viewer) and recipe.blocker(source) is None),
        "error": f"Не удалось создать {recipe.noun}. Можно попробовать ещё раз." if state == "failed" else None,
    }


async def generate(
    session, viewer, recipe: ArtworkRecipe, subject, request_key, regenerate, generator, translator, media_dir
):
    if not recipe.permitted(viewer):
        raise AccessDenied(recipe.denied)
    if generator is None:
        raise Conflict(f"генерация ({recipe.noun}) не настроена")
    source = await _source(session, viewer, recipe, subject)
    if reason := recipe.blocker(source):
        raise Conflict(reason)
    cid, sid = viewer.campaign.id, subject.id
    receipt = await session.scalar(
        select(Artwork).where(
            Artwork.campaign_id == cid, Artwork.kind == recipe.kind, Artwork.request_key == request_key
        )
    )
    if receipt:
        if receipt.subject_id != sid:
            raise Conflict("этот запрос уже использован")
        if receipt.status == "ready":
            return await status(session, viewer, recipe, subject, True)
        if receipt.status == "failed" or as_utc(receipt.lease_until) < now():
            raise Conflict("предыдущая попытка не завершена; начните новую попытку")
        raise ArtworkPending(recipe.noun)
    current = await status(session, viewer, recipe, subject, True)
    if current["image_url"] and not regenerate:
        return current
    await session.execute(
        update(Artwork)
        .where(
            Artwork.campaign_id == cid,
            Artwork.kind == recipe.kind,
            Artwork.subject_id == sid,
            Artwork.status == "pending",
            Artwork.lease_until < now(),
        )
        .values(status="failed", error="expired")
        .execution_options(synchronize_session="fetch")
    )
    await session.commit()
    seconds = getattr(generator, "timeout_seconds", 600)
    lease_seconds = seconds + 2 * getattr(translator, "timeout_seconds", 20) + 90
    job = Artwork(
        id=new_id("aw"),
        campaign_id=cid,
        kind=recipe.kind,
        subject_id=sid,
        request_key=request_key,
        source_digest=digest(source),
        status="pending",
        lease_until=now() + timedelta(seconds=lease_seconds),
    )
    audit = LlmCall(
        campaign_id=cid, purpose=recipe.purpose, model=generator.model, error="interrupted", cost_known=False
    )
    session.add_all([job, audit])
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ArtworkPending(recipe.noun) from exc
    # Another request may have completed between the initial cache read and our claim.
    if not regenerate:
        cached = await status(session, viewer, recipe, subject, True)
        if cached["image_url"]:
            await session.delete(job)
            await session.delete(audit)
            await session.commit()
            return await status(session, viewer, recipe, subject, True)
    path = media_dir / recipe.media_subdir / job.id
    reply = None
    started = time.monotonic()
    try:
        description = recipe.prompt_source(source)
        prepared = await translator.translate(session, description, cid) if translator else description
        init = recipe.init_image(source)
        async with asyncio.timeout(seconds + 10):
            control = recipe.control_image(source) if recipe.control_image else None
            extra = {} if control is None else {"control_image": control}
            if recipe.options:
                extra.update(recipe.options(source))
            if init is None:
                reply = await generator.generate(prepared, **extra)
            else:
                reply = await generator.generate(prepared, init_image=init, **extra)
        validate_image(reply.data, reply.mime)
        await session.refresh(subject)
        if digest(await _source(session, viewer, recipe, subject)) != job.source_digest:
            raise PortraitError("stale_source")
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, reply.data)
        changed = await session.execute(
            update(Artwork)
            .where(Artwork.id == job.id, Artwork.status == "pending", Artwork.lease_until >= now())
            .values(status="ready", mime=reply.mime, error=None)
            .execution_options(synchronize_session="fetch")
        )
        if changed.rowcount != 1:
            raise PortraitError("expired")
        audit.error = None
    except Exception as exc:
        reason = str(exc) if isinstance(exc, PortraitError) else "generation_error"
        await session.execute(
            update(Artwork)
            .where(Artwork.id == job.id, Artwork.status == "pending")
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
        raise Conflict(
            f"Описание места изменилось. Попробуйте создать {recipe.noun} ещё раз."
            if audit.error == "stale_source"
            else f"Не удалось создать {recipe.noun}. Прежняя картинка сохранена; проверьте ComfyUI и попробуйте ещё раз."
        )
    return await status(session, viewer, recipe, subject, True)


async def read_image(session, viewer, recipe: ArtworkRecipe, subject, image_id, media_dir):
    image = await session.get(Artwork, image_id)
    if (
        not image
        or image.kind != recipe.kind
        or image.subject_id != subject.id
        or image.campaign_id != viewer.campaign.id
        or image.status != "ready"
    ):
        raise NotFound("картинка не найдена")
    path = media_dir / recipe.media_subdir / image.id
    if not path.is_file():
        raise NotFound("файл картинки не найден")
    return path, image.mime
