"""REST: герои в профиле игрока, вне кампаний."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import Field

from app.api.deps import SessionDep, UserDep
from app.core import library as svc
from app.core.universal.editing import HeroEdit, apply_hero_edit, confirm_edit, propose_hero_edit
from app.core.universal.state import card_of, hero_card
from app.rules.universal.contracts import ClosedModel, HeroCard

router = APIRouter(prefix="/api/me", tags=["profile"])


class RequestKey(ClosedModel):
    request_key: str = Field(min_length=1, max_length=128)


class EditIn(RequestKey):
    edit: HeroEdit


class ChatEditIn(ClosedModel):
    message: str = Field(min_length=1, max_length=4000)
    expected_revision: int = Field(ge=1)


class EquipmentIn(ClosedModel):
    expected_revision: int = Field(ge=1)


@router.post("/characters/{library_id}/equipment-proposals", status_code=201)
async def propose_equipment(
    library_id: str,
    body: EquipmentIn,
    user: UserDep,
    session: SessionDep,
    request: Request,
) -> dict:
    draft = await propose_hero_edit(
        session,
        user.id,
        library_id,
        "Подбери новый стартовый набор по моему описанию: одно обычное оружие и одну обычную броню.",
        body.expected_revision,
        llm=request.app.state.hero_llm,
        equipment_only=True,
    )
    return dict(id=draft.id, edit=draft.proposal)


@router.patch("/characters/{library_id}", response_model=HeroCard)
async def edit_hero(library_id: str, body: EditIn, user: UserDep, session: SessionDep) -> dict:
    return await apply_hero_edit(session, user.id, library_id, body.edit, body.request_key)


@router.post("/characters/{library_id}/edit-proposals", status_code=201)
async def propose(library_id: str, body: ChatEditIn, user: UserDep, session: SessionDep, request: Request) -> dict:
    draft = await propose_hero_edit(
        session, user.id, library_id, body.message, body.expected_revision, llm=request.app.state.hero_llm
    )
    return dict(id=draft.id, edit=draft.proposal, explanations=draft.transcript[-1]["explanations"])


@router.post("/characters/{library_id}/edit-proposals/{proposal_id}/confirm", response_model=HeroCard)
async def confirm(library_id: str, proposal_id: str, body: RequestKey, user: UserDep, session: SessionDep) -> dict:
    return await confirm_edit(session, user.id, library_id, proposal_id, body.request_key)


@router.get("/characters", response_model=list[HeroCard])
async def list_heroes(user: UserDep, session: SessionDep) -> list[dict]:
    return [card_of(lc) for lc in await svc.list_mine(session, user)]


@router.get("/characters/{library_id}", response_model=HeroCard)
async def get_hero(library_id: str, user: UserDep, session: SessionDep) -> dict:
    return await hero_card(session, user.id, library_id)


@router.delete("/characters/{library_id}", status_code=204)
async def delete_hero(library_id: str, user: UserDep, session: SessionDep) -> Response:
    """Удаляется только герой профиля; его копии в кампаниях остаются."""
    await session.delete(await svc.get_mine(session, user, library_id))
    await session.commit()
    return Response(status_code=204)
