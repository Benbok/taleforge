from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import SessionDep, UserDep
from app.core import equipment_artwork as service
from app.core.campaigns import AccessDenied, get_viewer, is_admin
from app.core.characters import get_character
from app.core.equipment_artwork_scope import ArtworkScope

PREFIX = "/api/campaigns/{campaign_id}/characters/{hero_id}/items/{item_id}/artwork"
router = APIRouter(prefix=PREFIX, tags=["equipment-artwork"])


class EquipmentArtworkIn(BaseModel):
    request_key: str = Field(min_length=1, max_length=128)
    regenerate: bool = False


class EquipmentArtworkOut(BaseModel):
    status: Literal["idle", "pending", "ready", "failed"]
    image_url: str | None
    thumbnail_url: str | None
    enabled: bool
    can_generate: bool
    can_regenerate: bool = False
    error: str | None


def with_permissions(result, admin):
    return {**result, "can_regenerate": bool(result["enabled"] and result["image_url"] and admin)}


def check_regeneration(body, user):
    if body.regenerate and not is_admin(user):
        raise AccessDenied("Пересоздавать изображения снаряжения может только администратор")


async def context(session, user, campaign_id, hero_id, item_id):
    viewer = await get_viewer(session, user, campaign_id)
    item = await service.available_item(session, viewer, hero_id, item_id)
    hero = await get_character(session, viewer, hero_id)
    scope = ArtworkScope(campaign_id, hero.owner_user_id if hero.sheet.get("source_library_id") else None)
    return (
        viewer,
        service.public_source(item),
        PREFIX.format(campaign_id=campaign_id, hero_id=hero_id, item_id=item_id),
        scope,
    )


@router.get("", response_model=EquipmentArtworkOut)
async def artwork_status(
    campaign_id: str,
    hero_id: str,
    item_id: str,
    user: UserDep,
    session: SessionDep,
    request: Request,
):
    admin = is_admin(user)
    viewer, source, base, scope = await context(session, user, campaign_id, hero_id, item_id)
    result = await service.status(
        session,
        scope,
        source,
        base,
        request.app.state.equipment_artwork_generator is not None,
    )
    return with_permissions(result, admin)


@router.post("", response_model=EquipmentArtworkOut)
async def create_artwork(
    campaign_id: str,
    hero_id: str,
    item_id: str,
    body: EquipmentArtworkIn,
    user: UserDep,
    session: SessionDep,
    request: Request,
):
    admin = is_admin(user)
    viewer, source, base, scope = await context(session, user, campaign_id, hero_id, item_id)
    check_regeneration(body, user)
    try:
        result = await service.generate(
            session,
            viewer,
            hero_id,
            item_id,
            source,
            base,
            body.request_key,
            request.app.state.equipment_artwork_generator,
            request.app.state.equipment_artwork_translator,
            request.app.state.equipment_artwork_media_dir,
            scope=scope,
            regenerate=body.regenerate,
        )
        return with_permissions(result, admin)
    except service.ArtworkPending as exc:
        raise HTTPException(409, detail={"code": "artwork_pending", "message": str(exc)}) from exc


async def serve(campaign_id, hero_id, item_id, image_id, user, session, request, small=False):
    _, source, _, scope = await context(session, user, campaign_id, hero_id, item_id)
    path, mime = await service.read_image(
        session,
        scope,
        source,
        image_id,
        request.app.state.equipment_artwork_media_dir,
        small,
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


@router.get("/{image_id}")
async def image(
    campaign_id: str,
    hero_id: str,
    item_id: str,
    image_id: str,
    user: UserDep,
    session: SessionDep,
    request: Request,
):
    return await serve(campaign_id, hero_id, item_id, image_id, user, session, request)


@router.get("/{image_id}/thumbnail")
async def preview(
    campaign_id: str,
    hero_id: str,
    item_id: str,
    image_id: str,
    user: UserDep,
    session: SessionDep,
    request: Request,
):
    return await serve(campaign_id, hero_id, item_id, image_id, user, session, request, small=True)
