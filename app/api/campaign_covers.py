from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import SessionDep, UserDep
from app.core import campaign_covers as covers
from app.core.artwork import service
from app.core.campaigns import get_viewer

router = APIRouter(prefix="/api/campaigns/{campaign_id}/cover", tags=["campaign-covers"])

HEADERS = {
    "Cache-Control": "private, max-age=3600",
    "Vary": "Authorization",
    "X-Content-Type-Options": "nosniff",
}


class CoverIn(BaseModel):
    request_key: str = Field(min_length=1, max_length=128)
    regenerate: bool = False


class CoverOut(BaseModel):
    status: Literal["idle", "pending", "ready", "failed"]
    image_url: str | None
    thumbnail_url: str | None
    inherited: bool = False  # shown cover belongs to the world; the campaign has none of its own
    stale: bool
    enabled: bool
    can_generate: bool
    error: str | None


@router.get("", response_model=CoverOut)
async def cover_status(campaign_id: str, user: UserDep, session: SessionDep, request: Request):
    viewer = await get_viewer(session, user, campaign_id)
    return await covers.status(session, viewer, request.app.state.campaign_cover_generator is not None)


@router.post("", response_model=CoverOut)
async def create_cover(campaign_id: str, body: CoverIn, user: UserDep, session: SessionDep, request: Request):
    viewer = await get_viewer(session, user, campaign_id)
    state = request.app.state
    try:
        await service.generate(
            session,
            viewer,
            covers.RECIPE,
            viewer.campaign,
            body.request_key,
            body.regenerate,
            state.campaign_cover_generator,
            state.campaign_cover_translator,
            state.campaign_cover_media_dir,
        )
    except service.ArtworkPending as exc:
        raise HTTPException(409, detail={"code": "artwork_pending", "message": str(exc)}) from exc
    return await covers.status(session, viewer, True)


@router.get("/{image_id}")
async def image(campaign_id: str, image_id: str, user: UserDep, session: SessionDep, request: Request):
    viewer = await get_viewer(session, user, campaign_id)
    path, mime = await covers.read_cover(session, viewer, image_id, request.app.state.campaign_cover_media_dir)
    return FileResponse(path, media_type=mime, headers=HEADERS)


@router.get("/{image_id}/thumbnail")
async def thumbnail(campaign_id: str, image_id: str, user: UserDep, session: SessionDep, request: Request):
    viewer = await get_viewer(session, user, campaign_id)
    path, mime = await covers.read_thumbnail(session, viewer, image_id, request.app.state.campaign_cover_media_dir)
    return FileResponse(path, media_type=mime, headers=HEADERS)
