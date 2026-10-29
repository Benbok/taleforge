from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.api.deps import SessionDep, UserDep
from app.api.equipment_artwork import EquipmentArtworkIn, EquipmentArtworkOut, check_regeneration, with_permissions
from app.core import equipment_artwork as service
from app.core.campaigns import is_admin
from app.core.equipment_artwork_scope import library_item, library_scope

PREFIX = "/api/me/characters/{hero_id}/equipment/{kind}/artwork"
router = APIRouter(prefix=PREFIX, tags=["equipment-artwork"])


async def context(session, user, hero_id, kind):
    item = await library_item(session, user.id, hero_id, kind)
    scope = await library_scope(session, user.id, hero_id)
    return scope, service.public_source(item), PREFIX.format(hero_id=hero_id, kind=kind)


@router.get("", response_model=EquipmentArtworkOut)
async def status(hero_id: str, kind: str, session: SessionDep, user: UserDep, request: Request):
    admin = is_admin(user)
    scope, source, base = await context(session, user, hero_id, kind)
    enabled = request.app.state.equipment_artwork_generator is not None
    result = await service.status(session, scope, source, base, enabled)
    if result["image_url"]:
        image_id = result["image_url"].rsplit("/", 1)[-1]
        from app.db.models import EquipmentArtwork

        image = await session.get(EquipmentArtwork, image_id)
        if image.campaign_id is not None:
            # Save only existing immutable bytes: opening the library never calls a model.
            result = await service.save_cached(
                session,
                scope,
                source,
                base,
                "library-cache:" + image_id,
                result,
                request.app.state.equipment_artwork_media_dir,
            )
            result["enabled"] = enabled
            result["can_generate"] = False
    return with_permissions(result, admin)


@router.post("", response_model=EquipmentArtworkOut)
async def create(
    hero_id: str, kind: str, body: EquipmentArtworkIn, session: SessionDep, user: UserDep, request: Request
):
    admin = is_admin(user)
    scope, source, base = await context(session, user, hero_id, kind)
    check_regeneration(body, user)
    owner_id = user.id

    async def resolve_current():
        return await library_item(session, owner_id, hero_id, kind)

    try:
        result = await service.generate_scoped(
            session,
            scope,
            source,
            base,
            body.request_key,
            request.app.state.equipment_artwork_generator,
            request.app.state.equipment_artwork_translator,
            request.app.state.equipment_artwork_media_dir,
            resolve_current,
            regenerate=body.regenerate,
        )
        return with_permissions(result, admin)
    except service.ArtworkPending as exc:
        raise HTTPException(409, detail={"code": "artwork_pending", "message": str(exc)}) from exc


async def serve(hero_id, kind, image_id, session, user, request, small=False):
    scope, source, _ = await context(session, user, hero_id, kind)
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
async def image(hero_id: str, kind: str, image_id: str, session: SessionDep, user: UserDep, request: Request):
    return await serve(hero_id, kind, image_id, session, user, request)


@router.get("/{image_id}/thumbnail")
async def preview(hero_id: str, kind: str, image_id: str, session: SessionDep, user: UserDep, request: Request):
    return await serve(hero_id, kind, image_id, session, user, request, True)
