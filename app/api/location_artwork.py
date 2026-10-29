from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import SessionDep, UserDep
from app.core import location_artwork as service
from app.core.campaigns import get_viewer

router = APIRouter(prefix="/api/campaigns/{campaign_id}/locations/{location_id}/artwork", tags=["location-artwork"])


class LocationArtworkIn(BaseModel):
    request_key: str = Field(min_length=1, max_length=128)
    regenerate: bool = False


class LocationArtworkOut(BaseModel):
    status: Literal["idle", "pending", "ready", "failed"]
    image_url: str | None
    stale: bool
    enabled: bool
    can_generate: bool
    error: str | None


@router.get("", response_model=LocationArtworkOut)
async def artwork_status(campaign_id: str, location_id: str, user: UserDep, session: SessionDep, request: Request):
    viewer = await get_viewer(session, user, campaign_id)
    location = await service.current_location(session, viewer, location_id)
    return await service.status(session, viewer, location, request.app.state.location_artwork_generator is not None)


@router.post("", response_model=LocationArtworkOut)
async def create_artwork(
    campaign_id: str,
    location_id: str,
    body: LocationArtworkIn,
    user: UserDep,
    session: SessionDep,
    request: Request,
):
    viewer = await get_viewer(session, user, campaign_id)
    location = await service.current_location(session, viewer, location_id)
    try:
        return await service.generate(
            session,
            viewer,
            location,
            body.request_key,
            body.regenerate,
            request.app.state.location_artwork_generator,
            request.app.state.location_artwork_translator,
            request.app.state.location_artwork_media_dir,
        )
    except service.ArtworkPending as exc:
        raise HTTPException(409, detail={"code": "artwork_pending", "message": str(exc)}) from exc


@router.get("/{image_id}")
async def image(
    campaign_id: str,
    location_id: str,
    image_id: str,
    user: UserDep,
    session: SessionDep,
    request: Request,
):
    viewer = await get_viewer(session, user, campaign_id)
    location = await service.current_location(session, viewer, location_id)
    path, mime = await service.read_image(
        session,
        viewer,
        location,
        image_id,
        request.app.state.location_artwork_media_dir,
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
