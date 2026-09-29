"""REST: создание персонажа, лист, проверка мастером (ТЗ, раздел 5.1).

Свой лист целиком видят игрок и мастер, остальные — только публичную часть (раздел 2).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.content.catalog import campaign_catalog
from app.core import bonds
from app.core import characters as svc
from app.core import library as lib
from app.core.campaigns import AccessDenied, Conflict, Viewer, get_viewer, master_seat
from app.db.models import ActiveEffect, Character, InventoryItem
from app.gateway.events import envelope

router = APIRouter(prefix="/api/campaigns/{campaign_id}", tags=["characters"])


class CharacterIn(BaseModel):
    name: str | None = Field(None, max_length=64)
    class_id: str | None = None
    origin_id: str | None = None
    ability_method: Literal["standard_array", "point_buy", "roll"] | None = None
    abilities: dict[str, int] | None = None
    ability_choice: list[str] | None = None
    skills: list[str] | None = None
    equipment_choices: list[dict[str, Any]] | None = None
    public_bio: str | None = Field(None, max_length=4000)
    private_backstory: str | None = Field(None, max_length=4000)
    personality: dict[str, str] | None = None


class PreviewIn(CharacterIn):
    ability_rolls: list[int] | None = Field(None, max_length=6)  # выпавшие 4d6 черновика: только для живого листа


class ReviewIn(BaseModel):
    approve: bool
    comment: str = Field("", max_length=2000)


async def _view(session, viewer: Viewer, ch: Character) -> dict:
    out = await _sheet_view(session, viewer, ch)
    cat = await campaign_catalog(session, viewer.campaign)
    for key, kind in (("class", "class"), ("origin", "origin")):
        rec = cat.find((ch.sheet or {}).get(f"{key}_id") or "", kind)
        out[f"{key}_name"] = rec.name if rec else None
    if ch.status == "submitted":
        ai = master_seat(viewer.campaign).occupant_type == "agent"
        out["reviewer"] = "ai" if ai else "master"
        out["review_error"] = await svc.review_failure(session, ch) if ai else None
    return out


async def _sheet_view(session, viewer: Viewer, ch: Character) -> dict:
    mine = viewer.seat is not None and ch.seat_id == viewer.seat.id
    # заготовку без игрока показываем целиком: игрок выбирает, кем играть
    if not (mine or viewer.can_review or ch.status == "premade" or (viewer.is_owner and ch.seat_id is None)):
        return svc.public_view(ch)
    cat = await campaign_catalog(session, viewer.campaign)
    inv = (await session.scalars(select(InventoryItem).where(InventoryItem.character_id == ch.id))).all()
    eff = (await session.scalars(select(ActiveEffect).where(ActiveEffect.target_id == ch.id))).all()
    out = svc.full_view(ch, cat, list(inv), list(eff))
    if (ch.status == "draft" and mine) or ch.status == "premade":
        out["errors"] = svc.errors_for(ch, cat, await svc.creation_rules(session, viewer.campaign))
    return out


@router.get("/character-options")
async def character_options(campaign_id: str, user: UserDep, session: SessionDep) -> dict:
    v = await get_viewer(session, user, campaign_id)
    return await svc.options(session, v.campaign, await campaign_catalog(session, v.campaign))


@router.post("/character-preview")
async def character_preview(campaign_id: str, body: PreviewIn, user: UserDep, session: SessionDep) -> dict:
    """Живой лист конструктора по правилам кампании: ничего не сохраняет."""
    v = await get_viewer(session, user, campaign_id)
    cat = await campaign_catalog(session, v.campaign)
    return svc.preview(body.model_dump(exclude_none=True), cat, await svc.creation_rules(session, v.campaign))


@router.get("/characters")
async def list_characters(campaign_id: str, user: UserDep, session: SessionDep) -> list[dict]:
    v = await get_viewer(session, user, campaign_id)
    rows = (await session.scalars(select(Character).where(Character.campaign_id == campaign_id))).all()
    out = []
    for ch in rows:
        mine = v.seat is not None and ch.seat_id == v.seat.id
        hidden = ch.status == "draft" and not (mine or v.is_master)
        hidden = hidden or ch.status == "submitted" and not (mine or v.can_review)
        if hidden:
            continue  # чужие черновики не видны; героя на проверке видит тот, кто может его проверить
        out.append(await _view(session, v, ch))
    return out


@router.post("/characters", status_code=201)
async def create_character(campaign_id: str, body: CharacterIn, user: UserDep, session: SessionDep) -> dict:
    v = await get_viewer(session, user, campaign_id)
    rules = await svc.creation_rules(session, v.campaign)
    ch = await svc.create_draft(session, v, body.model_dump(exclude_none=True), rules)
    await session.commit()
    return await _view(session, v, ch)


@router.get("/characters/{character_id}")
async def get_character(campaign_id: str, character_id: str, user: UserDep, session: SessionDep) -> dict:
    v = await get_viewer(session, user, campaign_id)
    return await _view(session, v, await svc.get_character(session, v, character_id))


@router.put("/characters/{character_id}")
async def update_character(
    campaign_id: str, character_id: str, body: CharacterIn, user: UserDep, session: SessionDep
) -> dict:
    v = await get_viewer(session, user, campaign_id)
    ch = await svc.update_draft(
        session, v, await svc.get_character(session, v, character_id), body.model_dump(exclude_none=True)
    )
    await session.commit()
    return await _view(session, v, ch)


@router.post("/characters/{character_id}/roll-abilities")
async def roll_abilities(campaign_id: str, character_id: str, user: UserDep, session: SessionDep, request: Request):
    v = await get_viewer(session, user, campaign_id)
    ch = await svc.get_character(session, v, character_id)
    totals = await svc.roll_abilities(session, v, ch, request.app.state.dice_factory())
    await session.commit()
    return {"rolls": totals}


@router.post("/characters/{character_id}/submit")
async def submit(campaign_id: str, character_id: str, user: UserDep, session: SessionDep, request: Request) -> dict:
    v = await get_viewer(session, user, campaign_id)
    ch = await svc.get_character(session, v, character_id)
    cat = await campaign_catalog(session, v.campaign)
    errors = await svc.submit(session, v, ch, cat, await svc.creation_rules(session, v.campaign))
    await session.commit()
    if errors:
        return {"status": ch.status, "errors": errors}
    bus = request.app.state.bus
    await bus.publish(campaign_id, envelope("character.updated", campaign_id, {"character": svc.public_view(ch)}), None)
    if ch.status == "submitted" and master_seat(v.campaign).occupant_type == "agent":
        # проверку ведёт ИИ-мастер; ответ придёт событием character.reviewed
        request.app.state.master.schedule_review(campaign_id, ch.id)
    return {"status": ch.status, "errors": []}


@router.post("/characters/{character_id}/review")
async def review(
    campaign_id: str, character_id: str, body: ReviewIn, user: UserDep, session: SessionDep, request: Request
) -> dict:
    v = await get_viewer(session, user, campaign_id)
    ch = await svc.get_character(session, v, character_id)
    await svc.review(session, v, ch, await campaign_catalog(session, v.campaign), body.approve, body.comment)
    await session.commit()
    view = await _view(session, v, ch)
    bus = request.app.state.bus
    await bus.publish(campaign_id, envelope("character.updated", campaign_id, {"character": svc.public_view(ch)}), None)
    if ch.seat_id:
        await bus.publish(
            campaign_id,
            envelope("character.reviewed", campaign_id, {"status": ch.status, "comment": ch.review_comment}),
            [ch.seat_id],
        )
    return view


@router.post("/characters/{character_id}/review/retry-ai", status_code=202)
async def retry_ai_review(
    campaign_id: str, character_id: str, user: UserDep, session: SessionDep, request: Request
) -> dict:
    """Ещё раз отдать героя на проверку ИИ-мастеру, например после смены модели."""
    v = await get_viewer(session, user, campaign_id)
    ch = await svc.get_character(session, v, character_id)
    mine = v.seat is not None and ch.seat_id == v.seat.id
    if not (mine or v.can_review):
        raise AccessDenied("повторить проверку может игрок героя, мастер или владелец")
    if ch.status != "submitted":
        raise Conflict("персонаж не на проверке")
    if master_seat(v.campaign).occupant_type != "agent":
        raise Conflict("героя проверяет живой мастер")
    request.app.state.master.schedule_review(campaign_id, ch.id)
    return {"status": ch.status}


# --- готовые герои и герои из профиля ---


@router.post("/premades", status_code=201)
async def create_premade(campaign_id: str, body: CharacterIn, user: UserDep, session: SessionDep) -> dict:
    v = await get_viewer(session, user, campaign_id)
    rules = await svc.creation_rules(session, v.campaign)
    ch = await svc.create_premade(session, v, body.model_dump(exclude_none=True), rules)
    await session.commit()
    return await _view(session, v, ch)


@router.put("/premades/{character_id}")
async def update_premade(
    campaign_id: str, character_id: str, body: CharacterIn, user: UserDep, session: SessionDep
) -> dict:
    v = await get_viewer(session, user, campaign_id)
    ch = await svc.get_character(session, v, character_id)
    await svc.update_premade(session, v, ch, body.model_dump(exclude_none=True))
    await session.commit()
    return await _view(session, v, ch)


@router.delete("/premades/{character_id}", status_code=204)
async def delete_premade(campaign_id: str, character_id: str, user: UserDep, session: SessionDep) -> Response:
    v = await get_viewer(session, user, campaign_id)
    await svc.delete_premade(session, v, await svc.get_character(session, v, character_id))
    await session.commit()
    return Response(status_code=204)


@router.post("/characters/{character_id}/claim")
async def claim(campaign_id: str, character_id: str, user: UserDep, session: SessionDep, request: Request) -> dict:
    v = await get_viewer(session, user, campaign_id)
    ch = await svc.get_character(session, v, character_id)
    cat = await campaign_catalog(session, v.campaign)
    await svc.claim(session, v, ch, cat, await svc.creation_rules(session, v.campaign))
    await session.commit()
    await request.app.state.bus.publish(
        campaign_id, envelope("character.updated", campaign_id, {"character": svc.public_view(ch)}), None
    )
    return await _view(session, v, ch)


@router.post("/characters/from-library/{library_id}", status_code=201)
async def from_library(campaign_id: str, library_id: str, user: UserDep, session: SessionDep) -> dict:
    """Копия героя из профиля — черновиком в кампании. Дальше его можно поправить и отправить мастеру."""
    v = await get_viewer(session, user, campaign_id)
    lc = await lib.get_mine(session, user, library_id)
    ch = await lib.copy_to_campaign(session, v, lc, await svc.creation_rules(session, v.campaign))
    await session.commit()
    return await _view(session, v, ch)


# --- связи героев (проект «Подготовка кампании», раздел 7.1) ---


class BondAnswerIn(BaseModel):
    id: str
    text: str = Field("", max_length=600)
    private: bool = False


class BondsIn(BaseModel):
    answers: list[BondAnswerIn] = Field(max_length=3)


async def _bonds_target(session, v: Viewer, character_id: str) -> tuple[Character, bool]:
    ch = await svc.get_character(session, v, character_id)
    mine = v.seat is not None and ch.seat_id == v.seat.id
    if not (mine or v.is_master or v.can_review):
        raise AccessDenied("вопросы о связях видят игрок героя и мастер")
    if ch.status in ("dead", "retired", "premade"):
        raise Conflict("у этого героя связей не спрашивают")
    return ch, mine


@router.get("/characters/{character_id}/bonds")
async def get_bonds(campaign_id: str, character_id: str, user: UserDep, session: SessionDep, request: Request):
    """Вопросы о связях. Первое открытие игроком даёт вопросы по умолчанию; ИИ-мастер с каркасом в фоне
    заменяет их своими, пока на них не ответили."""
    from app.agents import prelude

    v = await get_viewer(session, user, campaign_id)
    ch, mine = await _bonds_target(session, v, character_id)
    b = bonds.bonds_of(ch)
    changed = mine and bonds.ensure_questions(ch)
    ask = False
    if mine and bonds.bonds_of(ch).get("source") == "default" and not b.get("status"):
        cfg, _ = await prelude._ai_plan(session, v.campaign)
        if cfg is not None:
            b = bonds.bonds_of(ch)
            b["status"] = "asking"
            bonds._save(ch, b)
            changed = ask = True
    if changed:
        await session.commit()
    if ask:
        request.app.state.master.schedule_bonds(campaign_id, ch.id)
    return {"bonds": bonds.bonds_of(ch), "can_answer": mine}


@router.put("/characters/{character_id}/bonds")
async def answer_bonds(
    campaign_id: str, character_id: str, body: BondsIn, user: UserDep, session: SessionDep, request: Request
) -> dict:
    """Ответы игрока. Открытые ответы видят все за столом, личные — только игрок и мастер."""
    from app.agents import prelude

    v = await get_viewer(session, user, campaign_id)
    ch, mine = await _bonds_target(session, v, character_id)
    if not mine:
        raise AccessDenied("отвечает игрок героя")
    try:
        b = bonds.answer(ch, [a.model_dump() for a in body.answers])
    except bonds.BondsError as e:
        raise Conflict(str(e)) from e
    cfg, _ = await prelude._ai_plan(session, v.campaign)
    await session.commit()
    await prelude.publish_bonds(request.app.state.bus, v.campaign, ch)
    await request.app.state.bus.publish(
        campaign_id, envelope("character.updated", campaign_id, {"character": svc.public_view(ch)}), None
    )
    if cfg is not None and b.get("answers"):
        request.app.state.master.schedule_hook(campaign_id, ch.id)  # мастер тайно вплетает ответы в каркас
    return {"bonds": b, "can_answer": True}
