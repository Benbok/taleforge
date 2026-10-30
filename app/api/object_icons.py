from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import SessionDep, UserDep
from app.core import map_backdrop, object_icon
from app.core.artwork import service
from app.core.campaigns import NotFound, get_viewer
from app.db.models import Entity

router = APIRouter(prefix="/api/campaigns/{campaign_id}", tags=["object-icons"])


class ObjectIconIn(BaseModel):
    request_key: str = Field(min_length=1, max_length=128)
    regenerate: bool = False


class ObjectIconOut(BaseModel):
    status: Literal["idle", "pending", "ready", "failed"]
    image_url: str | None
    stale: bool
    enabled: bool
    can_generate: bool
    error: str | None


class ObjectIconItem(ObjectIconOut):
    id: str
    name: str


class ObjectIconList(BaseModel):
    enabled: bool
    can_generate: bool
    objects: list[ObjectIconItem]


async def _object(session, viewer, object_id):
    row = await session.get(Entity, object_id)
    if row is None or row.campaign_id != viewer.campaign.id or row.kind != "object" or not row.location_id:
        raise NotFound("предмет недоступен")
    location = await map_backdrop.current_area(session, viewer, row.location_id)
    return await object_icon.visible_object(session, viewer, location, object_id)


@router.get("/locations/{location_id}/object-icons", response_model=ObjectIconList)
async def list_icons(campaign_id: str, location_id: str, user: UserDep, session: SessionDep, request: Request):
    viewer = await get_viewer(session, user, campaign_id)
    location = await map_backdrop.current_area(session, viewer, location_id)
    enabled = request.app.state.object_icon_generator is not None
    items = []
    for row in await object_icon.public_objects(session, viewer, location):
        status = await service.status(session, viewer, object_icon.RECIPE, row, enabled)
        items.append({"id": row.id, "name": row.name, **status})
    return {"enabled": enabled, "can_generate": bool(enabled and object_icon.RECIPE.permitted(viewer)), "objects": items}


@router.post("/objects/{object_id}/icon", response_model=ObjectIconOut)
async def create_icon(
    campaign_id: str, object_id: str, body: ObjectIconIn, user: UserDep, session: SessionDep, request: Request
):
    viewer = await get_viewer(session, user, campaign_id)
    row = await _object(session, viewer, object_id)
    try:
        return await service.generate(
            session,
            viewer,
            object_icon.RECIPE,
            row,
            body.request_key,
            body.regenerate,
            request.app.state.object_icon_generator,
            request.app.state.object_icon_translator,
            request.app.state.object_icon_media_dir,
        )
    except service.ArtworkPending as exc:
        raise HTTPException(409, detail={"code": "artwork_pending", "message": str(exc)}) from exc


@router.get("/objects/{object_id}/icon/{image_id}")
async def icon_image(
    campaign_id: str, object_id: str, image_id: str, user: UserDep, session: SessionDep, request: Request
):
    viewer = await get_viewer(session, user, campaign_id)
    row = await _object(session, viewer, object_id)
    path, mime = await service.read_image(
        session, viewer, object_icon.RECIPE, row, image_id, request.app.state.object_icon_media_dir
    )
    return FileResponse(
        path,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=3600", "Vary": "Authorization", "X-Content-Type-Options": "nosniff"},
    )
