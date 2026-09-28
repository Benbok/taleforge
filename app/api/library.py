"""REST: герои в профиле игрока, вне кампаний."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.characters import CharacterIn
from app.api.deps import SessionDep, UserDep
from app.core import characters as chars
from app.core import library as svc

router = APIRouter(prefix="/api/me", tags=["profile"])


@router.get("/character-options")
async def character_options(user: UserDep, session: SessionDep) -> dict:
    """Варианты конструктора по базовым правилам SRD (без правил конкретной кампании)."""
    return await chars.options_for_rules(svc.LIBRARY_RULES, await svc.base_catalog(session))


@router.get("/characters")
async def list_heroes(user: UserDep, session: SessionDep) -> list[dict]:
    cat = await svc.base_catalog(session)
    return [svc.view(lc, cat) for lc in await svc.list_mine(session, user)]


@router.post("/characters", status_code=201)
async def create_hero(body: CharacterIn, user: UserDep, session: SessionDep) -> dict:
    lc = await svc.create(session, user, body.model_dump(exclude_none=True))
    await session.commit()
    return svc.view(lc, await svc.base_catalog(session))


@router.get("/characters/{library_id}")
async def get_hero(library_id: str, user: UserDep, session: SessionDep) -> dict:
    return await svc.detail(session, await svc.get_mine(session, user, library_id), await svc.base_catalog(session))


@router.put("/characters/{library_id}")
async def update_hero(library_id: str, body: CharacterIn, user: UserDep, session: SessionDep) -> dict:
    lc = await svc.update(session, await svc.get_mine(session, user, library_id), body.model_dump(exclude_none=True))
    await session.commit()
    return svc.view(lc, await svc.base_catalog(session))


@router.delete("/characters/{library_id}", status_code=204)
async def delete_hero(library_id: str, user: UserDep, session: SessionDep) -> Response:
    """Удаляется только герой профиля; его копии в кампаниях остаются."""
    await session.delete(await svc.get_mine(session, user, library_id))
    await session.commit()
    return Response(status_code=204)


@router.post("/characters/{library_id}/roll-abilities")
async def roll_abilities(library_id: str, user: UserDep, session: SessionDep, request: Request) -> dict:
    lc = await svc.get_mine(session, user, library_id)
    totals = await svc.roll(session, lc, request.app.state.dice_factory())
    await session.commit()
    return {"rolls": totals}
