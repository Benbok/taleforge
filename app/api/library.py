"""REST: герои в профиле игрока, вне кампаний."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import Field

from app.api.characters import CharacterIn, PreviewIn
from app.api.deps import SessionDep, UserDep
from app.core import characters as chars
from app.core import library as svc
from app.core.universal.state import card_of, hero_card
from app.core.campaigns import Conflict
from app.core.universal.editing import HeroEdit, apply_hero_edit, confirm_edit, propose_hero_edit
from app.rules.universal.contracts import ClosedModel, HeroCard

router = APIRouter(prefix="/api/me", tags=["profile"])


class LibraryHeroIn(CharacterIn):
    pack_id: str | None = Field(None, max_length=64)  # мир героя; пустая строка — базовые правила


class LibraryPreviewIn(PreviewIn):
    pack_id: str | None = Field(None, max_length=64)


class RequestKey(ClosedModel):
    request_key: str = Field(min_length=1, max_length=128)


class EditIn(RequestKey):
    edit: HeroEdit


class ChatEditIn(ClosedModel):
    message: str = Field(min_length=1, max_length=4000)
    expected_revision: int = Field(ge=1)


@router.patch('/characters/{library_id}', response_model=HeroCard)
async def edit_hero(library_id: str, body: EditIn, user: UserDep, session: SessionDep) -> dict:
    return await apply_hero_edit(session, user.id, library_id, body.edit, body.request_key)


@router.post('/characters/{library_id}/edit-proposals', status_code=201)
async def propose(library_id: str, body: ChatEditIn, user: UserDep, session: SessionDep, request: Request) -> dict:
    draft = await propose_hero_edit(session, user.id, library_id, body.message, body.expected_revision,
                                    llm=request.app.state.hero_llm)
    return dict(id=draft.id, edit=draft.proposal, explanations=draft.transcript[-1]['explanations'])


@router.post('/characters/{library_id}/edit-proposals/{proposal_id}/confirm', response_model=HeroCard)
async def confirm(library_id: str, proposal_id: str, body: RequestKey, user: UserDep, session: SessionDep) -> dict:
    return await confirm_edit(session, user.id, library_id, proposal_id, body.request_key)


@router.get("/worlds")
async def list_worlds(user: UserDep, session: SessionDep) -> list[dict]:
    """Миры, для которых можно собрать героя профиля: базовые правила и загруженные пакеты миров."""
    return []


@router.get("/character-options")
async def character_options(user: UserDep, session: SessionDep, pack: str | None = None) -> dict:
    """Варианты конструктора для мира героя: без pack — базовые правила SRD, иначе классы и происхождения мира."""
    raise Conflict('Герой создаётся из описания через диалог с мастером.')


@router.post("/character-preview")
async def character_preview(body: LibraryPreviewIn, user: UserDep, session: SessionDep) -> dict:
    """Живой лист героя профиля по правилам его мира: ничего не сохраняет."""
    raise Conflict('Используйте универсальную карточку героя.')


@router.get("/characters", response_model=list[HeroCard])
async def list_heroes(user: UserDep, session: SessionDep) -> list[dict]:
    return [card_of(lc) for lc in await svc.list_mine(session, user)]


@router.post("/characters", status_code=201)
async def create_hero(body: LibraryHeroIn, user: UserDep, session: SessionDep) -> dict:
    raise Conflict('Создайте героя через диалог с мастером.')


@router.get("/characters/{library_id}", response_model=HeroCard)
async def get_hero(library_id: str, user: UserDep, session: SessionDep) -> dict:
    return await hero_card(session, user.id, library_id)


@router.put("/characters/{library_id}")
async def update_hero(library_id: str, body: LibraryHeroIn, user: UserDep, session: SessionDep) -> dict:
    raise Conflict('Используйте редактор базовой карточки с подтверждением версии.')


@router.delete("/characters/{library_id}", status_code=204)
async def delete_hero(library_id: str, user: UserDep, session: SessionDep) -> Response:
    """Удаляется только герой профиля; его копии в кампаниях остаются."""
    await session.delete(await svc.get_mine(session, user, library_id))
    await session.commit()
    return Response(status_code=204)


@router.post("/characters/{library_id}/roll-abilities")
async def roll_abilities(library_id: str, user: UserDep, session: SessionDep, request: Request) -> dict:
    raise Conflict('Допустима только перестановка набора 15, 14, 13, 12, 10, 8.')
