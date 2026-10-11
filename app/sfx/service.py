"""Durable admission and cache. Callers commit; inference never runs here."""

from __future__ import annotations

import secrets

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.campaigns import Conflict, NotFound
from app.db.models import SfxAsset, SfxJob, SfxLock, SfxSound, new_id
from app.sfx.contracts import SfxInput, cache_key, parameters
from app.sfx.storage import asset_path

ACTIVE = ("staged", "queued", "running")


def insert_for(session):
    if session.bind.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    return insert


async def queue_lock(session: AsyncSession) -> SfxLock:
    # Upsert works on both supported databases, including fresh Base.metadata test databases.
    insert = insert_for(session)
    await session.execute(insert(SfxLock).values(id=1, lease_until=0).on_conflict_do_nothing(index_elements=["id"]))
    await session.execute(update(SfxLock).where(SfxLock.id == 1).values(lease_until=SfxLock.lease_until))
    return await session.get(SfxLock, 1, populate_existing=True)


async def get_sound(session: AsyncSession, campaign_id: str, sound_id: str) -> SfxSound:
    sound = await session.get(SfxSound, sound_id)
    if sound is None or sound.campaign_id != campaign_id:
        raise NotFound("сохранённый звук не найден")
    return sound


async def enqueue(
    session: AsyncSession,
    settings: Settings,
    campaign_id: str,
    a: SfxInput,
    *,
    regenerate_id: str | None = None,
    staged: bool = False,
) -> dict:
    requested = parameters(a, settings)
    key = cache_key(a, settings)
    # A game turn can hold its transaction across LLM calls. Never take the global inference/admission
    # lock in that transaction: stage locally, then let the worker admit committed jobs in a short lock.
    if not staged:
        await queue_lock(session)
    if a.sound_id or regenerate_id:
        sound = await get_sound(session, campaign_id, regenerate_id or a.sound_id)
    else:
        sound = await session.scalar(
            select(SfxSound).where(SfxSound.campaign_id == campaign_id, SfxSound.cache_key == key)
        )
        if sound is None:
            # A named entry may have been regenerated with newer model parameters.
            sound = await session.scalar(
                select(SfxSound)
                .join(SfxAsset, SfxSound.current_asset_id == SfxAsset.id)
                .where(SfxSound.campaign_id == campaign_id, SfxAsset.cache_key == key)
                .limit(1)
            )
    if sound and sound.current_asset_id and not regenerate_id:
        asset = await session.get(SfxAsset, sound.current_asset_id)
        if (
            asset
            and asset_path(settings, asset.id).is_file()
            and (a.sound_id or (asset.parameters or sound.parameters) == requested)
        ):
            return {"status": "cached", "sound_id": sound.id, "asset_id": asset.id}
    if not settings.sfx_enabled:
        return {"status": "skipped", "reason": "генерация звука выключена на сервере"}
    if requested["weights_digest"] == "unprepared":
        return {"status": "skipped", "reason": "веса SFX ещё не готовы; проверьте контейнер sfx и доступ Hugging Face"}
    if sound:
        job = await session.scalar(select(SfxJob).where(SfxJob.sound_id == sound.id, SfxJob.status.in_(ACTIVE)))
        if job:
            return {"status": "queued", "sound_id": sound.id, "job_id": job.id}
    count = await session.scalar(select(func.count()).select_from(SfxJob).where(SfxJob.status.in_(ACTIVE)))
    campaign_count = await session.scalar(
        select(func.count())
        .select_from(SfxJob)
        .join(SfxSound)
        .where(SfxSound.campaign_id == campaign_id, SfxJob.status.in_(ACTIVE))
    )
    if count >= settings.sfx_max_queue or campaign_count >= settings.sfx_campaign_queue:
        return {"status": "skipped", "reason": "очередь генерации заполнена"}
    used = await session.scalar(select(func.coalesce(func.sum(SfxAsset.size_bytes), 0)))
    if used >= settings.sfx_cache_max_bytes:
        return {"status": "skipped", "reason": "хранилище звуков заполнено; удалите ненужные версии"}
    if sound is None:
        # PostgreSQL may wait for a competing game transaction, but it never aborts this turn.
        await session.execute(
            insert_for(session)(SfxSound)
            .values(
                id=new_id("sf"),
                campaign_id=campaign_id,
                cache_key=key,
                title=a.title or (a.description or "")[:100],
                description=a.description,
                parameters=requested,
            )
            .on_conflict_do_nothing(index_elements=["campaign_id", "cache_key"])
        )
        sound = await session.scalar(
            select(SfxSound).where(SfxSound.campaign_id == campaign_id, SfxSound.cache_key == key)
        )
    if regenerate_id or a.sound_id:
        requested = parameters(
            SfxInput(
                description=sound.description,
                duration_seconds=sound.parameters["duration_seconds"],
                context=sound.parameters.get("context", ""),
            ),
            settings,
        )
    seed = secrets.randbelow(2**31 - 1) if regenerate_id else int(requested.get("seed", 0))
    inserted = await session.scalar(
        insert_for(session)(SfxJob)
        .values(
            id=new_id("sj"),
            sound_id=sound.id,
            seed=seed,
            parameters=requested,
            status="staged" if staged else "queued",
        )
        .on_conflict_do_nothing(
            index_elements=["sound_id"], index_where=text("status IN ('staged', 'queued', 'running')")
        )
        .returning(SfxJob.id)
    )
    if inserted:
        return {"status": "queued", "sound_id": sound.id, "job_id": inserted}
    # The conflicting job can finish (or be deleted) before this read; don't abort a game turn.
    job = await session.scalar(
        select(SfxJob).where(SfxJob.sound_id == sound.id).order_by(SfxJob.created_at.desc()).limit(1)
    )
    if job is None or job.status == "failed":
        return {"status": "skipped", "reason": "конкурентная генерация завершилась без результата"}
    if job.status == "ready":
        asset = await session.get(SfxAsset, job.asset_id)
        if asset and asset_path(settings, asset.id).is_file():
            return {"status": "cached", "sound_id": sound.id, "asset_id": asset.id}
        return {"status": "skipped", "reason": "готовый файл генерации недоступен"}
    return {"status": "queued", "sound_id": sound.id, "job_id": job.id}


def track(sound: SfxSound, asset: SfxAsset) -> dict:
    return {
        "id": asset.id,
        "title": sound.title,
        "layer": "sfx",
        "gain_db": -3.0,
        "url": f"/api/campaigns/{sound.campaign_id}/sfx/assets/{asset.id}",
    }


async def catalog(session: AsyncSession, settings: Settings, campaign_id: str) -> dict:
    sounds = (
        await session.scalars(
            select(SfxSound)
            .where(SfxSound.campaign_id == campaign_id)
            .order_by(SfxSound.pinned.desc(), SfxSound.created_at.desc())
            .limit(200)
        )
    ).all()
    ids = [s.id for s in sounds]
    assets = (
        (
            await session.scalars(
                select(SfxAsset).where(SfxAsset.sound_id.in_(ids)).order_by(SfxAsset.created_at.desc())
            )
        ).all()
        if ids
        else []
    )
    jobs = (
        (await session.scalars(select(SfxJob).where(SfxJob.sound_id.in_(ids)).order_by(SfxJob.created_at.desc()))).all()
        if ids
        else []
    )
    return {
        "enabled": settings.sfx_enabled,
        "backend": settings.sfx_backend,
        "device": settings.sfx_device,
        "prepared": parameters(SfxInput(description="Check model readiness"), settings)["weights_digest"]
        != "unprepared",
        "sounds": [
            {
                "id": s.id,
                "title": s.title,
                "description": s.description,
                "pinned": s.pinned,
                "duration_seconds": s.parameters["duration_seconds"],
                "current_asset_id": s.current_asset_id,
                "versions": [
                    {
                        **track(s, v),
                        "duration_seconds": v.duration_seconds,
                        "size_bytes": v.size_bytes,
                        "seed": v.seed,
                        "created_at": v.created_at.isoformat(),
                    }
                    for v in assets
                    if v.sound_id == s.id
                ],
                "job": next((job_view(j) for j in jobs if j.sound_id == s.id), None),
            }
            for s in sounds
        ],
    }


def job_view(job: SfxJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "attempts": job.attempts,
        "error": job.error,
        "elapsed_seconds": job.elapsed_seconds,
        "created_at": job.created_at.isoformat(),
    }


async def remove_sound(session: AsyncSession, campaign_id: str, sound_id: str) -> list[str]:
    await queue_lock(session)
    sound = await get_sound(session, campaign_id, sound_id)
    active = await session.scalar(select(SfxJob.id).where(SfxJob.sound_id == sound.id, SfxJob.status.in_(ACTIVE)))
    if active:
        raise Conflict("дождитесь завершения генерации перед удалением звука")
    ids = list((await session.scalars(select(SfxAsset.id).where(SfxAsset.sound_id == sound.id))).all())
    await session.delete(sound)
    return ids
