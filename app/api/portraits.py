from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field

from app.api.deps import SessionDep, UserDep
from app.core.campaigns import AccessDenied, Conflict, get_viewer
from app.core.characters import get_character, public_view
from app.core.universal.portraits import PortraitPending, generate, read_portrait
from app.core.universal.state import card_of, game_card_of, load_library_hero
from app.gateway.events import envelope
from app.rules.universal.contracts import ClosedModel, HeroCard, UniversalGameCard

router = APIRouter(tags=["portraits"])


class PortraitIn(ClosedModel):
    request_key: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=1)


async def _generate(request, session, user_id, hero, body):
    try:
        await generate(
            session,
            user_id,
            hero,
            body.request_key,
            body.expected_revision,
            request.app.state.portraits,
            request.app.state.portrait_media_dir,
            translator=getattr(request.app.state, "portrait_translator", None),
        )
    except PortraitPending as exc:
        raise HTTPException(409, detail={"code": "portrait_pending", "message": str(exc)}) from exc


@router.post("/api/me/characters/{hero_id}/portrait", response_model=HeroCard)
async def library_portrait(hero_id: str, body: PortraitIn, request: Request, user: UserDep, session: SessionDep):
    hero = await load_library_hero(session, user.id, hero_id)
    await _generate(request, session, user.id, hero, body)
    await session.refresh(hero)
    return card_of(hero)


@router.post("/api/campaigns/{campaign_id}/characters/{hero_id}/portrait", response_model=UniversalGameCard)
async def game_portrait(
    campaign_id: str, hero_id: str, body: PortraitIn, request: Request, user: UserDep, session: SessionDep
):
    viewer = await get_viewer(session, user, campaign_id)
    hero = await get_character(session, viewer, hero_id)
    if not viewer.is_owner and not (viewer.is_player and hero.seat_id == viewer.seat.id):
        raise AccessDenied("Портрет меняет игрок этого героя или владелец кампании.")
    if hero.sheet.get("rules_version") != "universal.v1":
        raise Conflict("Портрет доступен для универсального героя.")
    await _generate(request, session, user.id, hero, body)
    await session.refresh(hero)
    await request.app.state.bus.publish(
        campaign_id, envelope("character.updated", campaign_id, {"character": public_view(hero)}), None
    )
    return game_card_of(hero)


@router.get("/api/portraits/{portrait_id}")
async def portrait(portrait_id: str, request: Request, user: UserDep, session: SessionDep):
    path, mime = await read_portrait(session, user, portrait_id, request.app.state.portrait_media_dir)
    return FileResponse(
        path, media_type=mime, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}
    )
