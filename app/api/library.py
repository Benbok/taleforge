"""REST: герои в профиле игрока, вне кампаний."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import Field

from app.api.characters import CharacterIn, PreviewIn
from app.api.deps import SessionDep, UserDep
from app.core import characters as chars
from app.core import library as svc

router = APIRouter(prefix="/api/me", tags=["profile"])


class LibraryHeroIn(CharacterIn):
    pack_id: str | None = Field(None, max_length=64)  # мир героя; пустая строка — базовые правила


class LibraryPreviewIn(PreviewIn):
    pack_id: str | None = Field(None, max_length=64)


@router.get("/worlds")
async def list_worlds(user: UserDep, session: SessionDep) -> list[dict]:
    """Миры, для которых можно собрать героя профиля: базовые правила и загруженные пакеты миров."""
    return await svc.worlds(session)


@router.get("/character-options")
async def character_options(user: UserDep, session: SessionDep, pack: str | None = None) -> dict:
    """Варианты конструктора для мира героя: без pack — базовые правила SRD, иначе классы и происхождения мира."""
    w = await svc.world(session, pack)
    return await chars.options_for_rules(w.rules, w.cat)


@router.post("/character-preview")
async def character_preview(body: LibraryPreviewIn, user: UserDep, session: SessionDep) -> dict:
    """Живой лист героя профиля по правилам его мира: ничего не сохраняет."""
    w = await svc.world(session, body.pack_id)
    return chars.preview(body.model_dump(exclude_none=True), w.cat, w.rules)


@router.get("/characters")
async def list_heroes(user: UserDep, session: SessionDep) -> list[dict]:
    ws = svc.Worlds(session)
    return [svc.view(lc, await ws.of(lc)) for lc in await svc.list_mine(session, user)]


@router.post("/characters", status_code=201)
async def create_hero(body: LibraryHeroIn, user: UserDep, session: SessionDep) -> dict:
    data = body.model_dump(exclude_none=True)
    await svc.world(session, data.get("pack_id"))  # мир должен быть загружен
    lc = await svc.create(session, user, data)
    await session.commit()
    return svc.view(lc, await svc.Worlds(session).of(lc))


@router.get("/characters/{library_id}")
async def get_hero(library_id: str, user: UserDep, session: SessionDep) -> dict:
    lc = await svc.get_mine(session, user, library_id)
    return await svc.detail(session, lc, await svc.Worlds(session).of(lc))


@router.put("/characters/{library_id}")
async def update_hero(library_id: str, body: LibraryHeroIn, user: UserDep, session: SessionDep) -> dict:
    data = body.model_dump(exclude_none=True)
    if data.get("pack_id"):
        await svc.world(session, data["pack_id"])
    lc = await svc.update(session, await svc.get_mine(session, user, library_id), data)
    await session.commit()
    return svc.view(lc, await svc.Worlds(session).of(lc))


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
