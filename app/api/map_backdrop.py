from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import SessionDep, UserDep
from app.core import map_backdrop
from app.core.artwork import service
from app.core.campaigns import get_viewer

router = APIRouter(prefix="/api/campaigns/{campaign_id}/locations/{location_id}/map-backdrop", tags=["map-backdrop"])


class MapBackdropIn(BaseModel):
    request_key: str = Field(min_length=1, max_length=128)
    regenerate: bool = False


class MapBackdropOut(BaseModel):
    status: Literal["idle", "pending", "ready", "failed"]
    image_url: str | None
    stale: bool
    enabled: bool
    can_generate: bool
    error: str | None


@router.get("", response_model=MapBackdropOut)
async def backdrop_status(campaign_id: str, location_id: str, user: UserDep, session: SessionDep, request: Request):
    viewer = await get_viewer(session, user, campaign_id)
    location = await map_backdrop.current_area(session, viewer, location_id)
    enabled = request.app.state.map_backdrop_generator is not None
    return await service.status(session, viewer, map_backdrop.RECIPE, location, enabled)


@router.post("", response_model=MapBackdropOut)
async def create_backdrop(
    campaign_id: str,
    location_id: str,
    body: MapBackdropIn,
    user: UserDep,
    session: SessionDep,
    request: Request,
):
    viewer = await get_viewer(session, user, campaign_id)
    location = await map_backdrop.current_area(session, viewer, location_id)
    try:
        return await service.generate(
            session,
            viewer,
            map_backdrop.RECIPE,
            location,
            body.request_key,
            body.regenerate,
            request.app.state.map_backdrop_generator,
            request.app.state.map_backdrop_translator,
            request.app.state.map_backdrop_media_dir,
        )
    except service.ArtworkPending as exc:
        raise HTTPException(409, detail={"code": "artwork_pending", "message": str(exc)}) from exc


@router.get("/{image_id}")
async def image(campaign_id: str, location_id: str, image_id: str, user: UserDep, session: SessionDep, request: Request):
    viewer = await get_viewer(session, user, campaign_id)
    location = await map_backdrop.current_area(session, viewer, location_id)
    path, mime = await service.read_image(
        session, viewer, map_backdrop.RECIPE, location, image_id, request.app.state.map_backdrop_media_dir
    )
    return FileResponse(
        path,
        media_type=mime,
        headers={
            "Cache-Control": "private, max-age=3600",
            "Vary": "Authorization",
            "X-Content-Type-Options": "nosniff",
        },
    )
