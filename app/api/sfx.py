"""Campaign-scoped generated SFX management and immutable authorized downloads."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import SessionDep, UserDep
from app.core.campaigns import AccessDenied, Conflict, NotFound, get_viewer, is_admin
from app.db.models import SfxAsset, SfxJob, SfxSound
from app.sfx.contracts import SfxInput, parameters
from app.sfx.service import catalog, enqueue, get_sound, job_view, queue_lock, remove_sound
from app.sfx.storage import asset_path

router = APIRouter(prefix="/api", tags=["generated audio"])


class SoundPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    pinned: bool | None = None


async def owner(session, user, campaign_id):
    viewer = await get_viewer(session, user, campaign_id)
    if not viewer.is_owner:
        raise AccessDenied("управлять сохранёнными звуками может только владелец кампании")
    return viewer


@router.get("/campaigns/{campaign_id}/sfx")
async def sounds(campaign_id: str, request: Request, user: UserDep, session: SessionDep) -> dict[str, Any]:
    await get_viewer(session, user, campaign_id)
    return await catalog(session, request.app.state.settings, campaign_id)


@router.post("/campaigns/{campaign_id}/sfx", status_code=202)
async def generate(campaign_id: str, body: SfxInput, request: Request, user: UserDep, session: SessionDep) -> dict:
    await owner(session, user, campaign_id)
    receipt = await enqueue(session, request.app.state.settings, campaign_id, body)
    await session.commit()
    return receipt  # manual preview never broadcasts to players


@router.post("/campaigns/{campaign_id}/sfx/{sound_id}/regenerate", status_code=202)
async def regenerate(campaign_id: str, sound_id: str, request: Request, user: UserDep, session: SessionDep) -> dict:
    await owner(session, user, campaign_id)
    sound = await get_sound(session, campaign_id, sound_id)
    body = SfxInput(description=sound.description, duration_seconds=sound.parameters["duration_seconds"])
    receipt = await enqueue(session, request.app.state.settings, campaign_id, body, regenerate_id=sound_id)
    await session.commit()
    return receipt


@router.patch("/campaigns/{campaign_id}/sfx/{sound_id}")
async def patch_sound(campaign_id: str, sound_id: str, body: SoundPatch, user: UserDep, session: SessionDep) -> dict:
    await owner(session, user, campaign_id)
    await queue_lock(session)
    sound = await get_sound(session, campaign_id, sound_id)
    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise Conflict("название не может быть пустым")
        sound.title = title
    if body.pinned is not None:
        sound.pinned = body.pinned
    await session.commit()
    return {"id": sound.id, "title": sound.title, "pinned": sound.pinned}


@router.delete("/campaigns/{campaign_id}/sfx/{sound_id}", status_code=204)
async def delete_sound(campaign_id: str, sound_id: str, request: Request, user: UserDep, session: SessionDep) -> None:
    await owner(session, user, campaign_id)
    ids = await remove_sound(session, campaign_id, sound_id)
    await session.commit()
    for asset_id in ids:
        await asyncio.to_thread(asset_path(request.app.state.settings, asset_id).unlink, missing_ok=True)


@router.get("/campaigns/{campaign_id}/sfx/assets/{asset_id}")
async def generated_file(
    campaign_id: str, asset_id: str, request: Request, user: UserDep, session: SessionDep
) -> FileResponse:
    await get_viewer(session, user, campaign_id)
    asset = await session.get(SfxAsset, asset_id)
    sound = await session.get(SfxSound, asset.sound_id) if asset else None
    if not asset or not sound or sound.campaign_id != campaign_id:
        raise NotFound("звук не найден")
    path = asset_path(request.app.state.settings, asset.id)
    if not path.is_file():
        raise NotFound("файл звука отсутствует; регенерируйте эффект")
    return FileResponse(
        path,
        media_type="audio/ogg",
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "Vary": "Authorization",
            "ETag": f'"{asset.digest}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/admin/sfx")
async def status(request: Request, user: UserDep, session: SessionDep) -> dict:
    if not is_admin(user):
        raise AccessDenied("статистика доступна администратору")
    counts = (await session.execute(select(SfxJob.status, func.count()).group_by(SfxJob.status))).all()
    jobs = (await session.scalars(select(SfxJob).order_by(SfxJob.created_at.desc()).limit(50))).all()
    cfg = request.app.state.settings
    used = await session.scalar(select(func.coalesce(func.sum(SfxAsset.size_bytes), 0)))
    return {
        "enabled": cfg.sfx_enabled,
        "backend": cfg.sfx_backend,
        "device": cfg.sfx_device,
        "prepared": parameters(SfxInput(description="Check model readiness"), cfg)["weights_digest"] != "unprepared",
        "queue": dict(counts),
        "used_bytes": used,
        "max_bytes": cfg.sfx_cache_max_bytes,
        "max_queue": cfg.sfx_max_queue,
        "jobs": [job_view(j) for j in jobs],
    }
