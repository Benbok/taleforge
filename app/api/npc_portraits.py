from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import SessionDep, UserDep
from app.core import npc_portraits as service
from app.core.campaigns import NotFound, get_viewer

router = APIRouter(prefix="/api/campaigns/{campaign_id}/npcs/{npc_id}/portraits", tags=["npc-portraits"])


class GenerateIn(BaseModel):
    request_key: str = Field(min_length=1, max_length=128)


class SelectIn(BaseModel):
    image_id: str = Field(min_length=1, max_length=32)


class Variant(BaseModel):
    id: str
    image_url: str
    thumbnail_url: str


class PortraitsOut(BaseModel):
    status: Literal["idle", "pending", "ready", "failed"]
    selected_id: str | None
    variants: list[Variant]
    enabled: bool
    can_generate: bool
    can_select: bool
    error: str | None


async def context(session, user, campaign_id, npc_id):
    viewer = await get_viewer(session, user, campaign_id)
    return viewer, await service.source_for(session, viewer, npc_id)


@router.get("", response_model=PortraitsOut)
async def status(campaign_id: str, npc_id: str, session: SessionDep, user: UserDep, request: Request):
    viewer, source = await context(session, user, campaign_id, npc_id)
    return await service.status(session, viewer, npc_id, source, request.app.state.npc_portrait_generator is not None)


@router.post("", response_model=PortraitsOut)
async def generate(
    campaign_id: str, npc_id: str, body: GenerateIn, session: SessionDep, user: UserDep, request: Request
):
    viewer, source = await context(session, user, campaign_id, npc_id)
    try:
        return await service.generate(
            session,
            viewer,
            npc_id,
            source,
            body.request_key,
            request.app.state.npc_portrait_generator,
            request.app.state.npc_portrait_translator,
            request.app.state.npc_portrait_media_dir,
        )
    except service.PortraitPending as exc:
        raise HTTPException(409, detail={"code": "portrait_pending", "message": str(exc)}) from exc


@router.put("/selection", response_model=PortraitsOut)
async def select(campaign_id: str, npc_id: str, body: SelectIn, session: SessionDep, user: UserDep, request: Request):
    viewer, source = await context(session, user, campaign_id, npc_id)
    return await service.apply(
        session, viewer, npc_id, source, body.image_id, request.app.state.npc_portrait_generator is not None
    )


async def serve(campaign_id, npc_id, image_id, session, user, request, small=False):
    viewer, source = await context(session, user, campaign_id, npc_id)
    row = await service.candidate(session, viewer, npc_id, source, image_id)
    path = request.app.state.npc_portrait_media_dir / "npcs" / row.id
    if small:
        path = path.with_suffix(".webp")
    if not path.is_file():
        raise NotFound("Файл портрета недоступен")
    return FileResponse(
        path,
        media_type="image/webp" if small else row.mime,
        headers={
            "Cache-Control": "private, max-age=3600",
            "Vary": "Authorization",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{image_id}")
async def image(campaign_id: str, npc_id: str, image_id: str, session: SessionDep, user: UserDep, request: Request):
    return await serve(campaign_id, npc_id, image_id, session, user, request)


@router.get("/{image_id}/thumbnail")
async def thumbnail(campaign_id: str, npc_id: str, image_id: str, session: SessionDep, user: UserDep, request: Request):
    return await serve(campaign_id, npc_id, image_id, session, user, request, True)
