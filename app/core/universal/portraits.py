"""Immutable portrait storage and durable generation claims, outside gameplay state."""

import asyncio
import logging
import time
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.agents.portraits import PortraitError, validate_image
from app.core.campaigns import Conflict, NotFound
from app.db.models import HeroPortrait, LibraryCharacter, LlmCall, as_utc, new_id, now

log = logging.getLogger(__name__)
LEASE = timedelta(minutes=3)


class PortraitPending(Conflict):
    pass


def portrait_url(portrait_id: str | None) -> str | None:
    return f"/api/portraits/{portrait_id}" if portrait_id else None


async def generate(session, user_id, hero, request_key, expected_revision, generator, media_dir, translator=None):
    timeout_seconds = getattr(generator, "timeout_seconds", 125)
    lease = max(LEASE, timedelta(seconds=timeout_seconds + 30))
    model = type(hero)
    hero_id = hero.id
    revision = hero.revision if isinstance(hero, LibraryCharacter) else 1
    if revision != expected_revision:
        raise Conflict("Описание изменилось. Обновите карточку перед созданием портрета.")
    receipt = await session.scalar(
        select(HeroPortrait).where(HeroPortrait.owner_user_id == user_id, HeroPortrait.request_key == request_key)
    )
    if receipt:
        if receipt.target_id == hero_id and receipt.status == "ready":
            return
        if receipt.target_id == hero_id and receipt.status == "pending":
            raise PortraitPending("Портрет ещё создаётся. Проверьте результат чуть позже.")
        raise Conflict(
            "Этот запрос уже обработан или выполняется. Обновите карточку; новый вариант создаётся отдельным запросом."
        )
    if hero.portrait_job_id:
        pending = await session.get(HeroPortrait, hero.portrait_job_id)
        if pending and as_utc(pending.created_at) + lease > now():
            raise PortraitPending("Портрет уже создаётся. Дождитесь результата.")
        if pending and pending.status == "pending":
            pending.status = "failed"
    job = HeroPortrait(id=new_id("hp"), owner_user_id=user_id, target_id=hero_id, request_key=request_key)
    session.add(job)
    previous_job = hero.portrait_job_id
    description = dict(hero.sheet["description"])
    campaign_id = getattr(hero, "campaign_id", None)
    audit = LlmCall(
        campaign_id=campaign_id,
        purpose="hero_portrait",
        model=generator.model,
        cost_known=False,
        error="interrupted",
        diagnostics={"portrait_id": job.id},
    )
    session.add(audit)
    try:
        claim_conditions = [model.id == hero_id, model.portrait_job_id == previous_job]
        if isinstance(hero, LibraryCharacter):
            claim_conditions.append(model.revision == expected_revision)
        changed = await session.execute(update(model).where(*claim_conditions).values(portrait_job_id=job.id))
        if changed.rowcount != 1:
            raise Conflict("Портрет уже создаётся. Обновите карточку.")
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise PortraitPending("Этот запрос уже выполняется. Обновите карточку.") from exc

    reply = None
    started = time.monotonic()
    reason = None
    path = media_dir / "portraits" / job.id
    try:
        async with asyncio.timeout(timeout_seconds + 10):
            if translator:
                description = await translator.translate(session, description, campaign_id)
            reply = await generator.generate(description)
        validate_image(reply.data, reply.mime)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, reply.data)
        conditions = [model.id == hero_id, model.portrait_job_id == job.id]
        if isinstance(hero, LibraryCharacter):
            conditions.append(model.revision == expected_revision)
        changed = await session.execute(
            update(model).where(*conditions).values(portrait_id=job.id, portrait_job_id=None)
        )
        if changed.rowcount != 1:
            raise PortraitError("stale_hero")
        job.status = "ready"
        job.mime = reply.mime
    except Exception as exc:
        reply = reply or getattr(exc, "reply", None)
        reason = str(exc) if isinstance(exc, PortraitError) else "generation_error"
        audit.diagnostics = {"portrait_id": job.id, **getattr(exc, "diagnostics", {})}
        job.status = "failed"
        await session.execute(
            update(model).where(model.id == hero_id, model.portrait_job_id == job.id).values(portrait_job_id=None)
        )
        await asyncio.to_thread(path.unlink, missing_ok=True)
        log.warning("Hero portrait failed: %s (%s) %s", reason, type(exc).__name__, audit.diagnostics)
    audit.model = reply.model if reply else generator.model
    audit.tokens_in = reply.tokens_in if reply else 0
    audit.tokens_out = reply.tokens_out if reply else 0
    audit.tokens_reasoning = reply.tokens_reasoning if reply else 0
    audit.cost = reply.cost if reply else 0
    audit.cost_known = reply.cost_known if reply else False
    audit.latency_ms = int((time.monotonic() - started) * 1000)
    audit.error = reason
    await session.commit()
    if reason:
        messages = {
            "not_configured": "Генерация портретов пока не настроена на сервере.",
            "quota": "У сервиса изображений исчерпана квота. Попробуйте позже.",
            "stale_hero": "Описание изменилось во время генерации. Обновите карточку перед новой попыткой.",
            "comfyui_unavailable": "Локальный ComfyUI недоступен. Запустите его и попробуйте снова.",
            "comfyui_timeout": "ComfyUI не успел создать портрет. Проверьте его очередь перед новой попыткой.",
            "translation_unavailable": (
                "Не удалось перевести описание портрета. Попробуйте позже; прежний портрет сохранён."
            ),
            "translation_invalid": "Сервис не смог перевести описание на английский. Попробуйте позже.",
            "translation_timeout": "Сервис перевода не ответил вовремя. Попробуйте позже.",
        }
        raise Conflict(
            messages.get(reason, "Не удалось создать портрет. Прежнее изображение сохранено; попробуйте ещё раз.")
        )


async def read_portrait(session, user, portrait_id, media_dir):
    from app.core.campaigns import AccessDenied, get_viewer
    from app.db.models import Character

    image = await session.get(HeroPortrait, portrait_id)
    if not image or image.status != "ready":
        raise NotFound("портрет не найден")
    allowed = image.owner_user_id == user.id
    if not allowed:
        heroes = (await session.scalars(select(Character).where(Character.portrait_id == portrait_id))).all()
        for hero in heroes:
            try:
                await get_viewer(session, user, hero.campaign_id)
                allowed = True
                break
            except (AccessDenied, NotFound):
                continue
    if not allowed:
        raise NotFound("портрет не найден")
    path = media_dir / "portraits" / image.id
    if not path.is_file():
        raise NotFound("файл портрета не найден")
    return path, image.mime
