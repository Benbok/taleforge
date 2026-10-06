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
from app.core.campaigns import AccessDenied, Conflict, Viewer, get_viewer, master_seat, stand_in_seats
from app.core.views import CharacterView
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
    fighting_style: str | None = Field(None, max_length=40)
    expertise: list[str] | None = Field(None, max_length=8)
    equipment_choices: list[dict[str, Any]] | None = None
    cantrips: list[str] | None = Field(None, max_length=30)
    spells: list[str] | None = Field(None, max_length=80)
    prepared: list[str] | None = Field(None, max_length=60)
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
    # героя ушедшего игрока ведёт другой по итогам голосования: ему нужен лист, но не личная предыстория
    stand_in = ch.seat_id is not None and ch.seat_id in stand_in_seats(viewer.campaign, viewer.user.id)
    # заготовку без игрока показываем целиком: игрок выбирает, кем играть
    full = mine or viewer.can_review or ch.status == "premade" or (viewer.is_owner and ch.seat_id is None)
    if not (full or stand_in):
        return svc.public_view(ch)
    cat = await campaign_catalog(session, viewer.campaign)
    inv = (await session.scalars(select(InventoryItem).where(InventoryItem.character_id == ch.id))).all()
    eff = (await session.scalars(select(ActiveEffect).where(ActiveEffect.target_id == ch.id))).all()
    out = svc.full_view(ch, cat, list(inv), list(eff))
    if not full:
        out.pop("private_backstory", None)
        out["stand_in"] = True
    if (ch.status == "draft" and mine) or ch.status == "premade":
        out["errors"] = svc.errors_for(ch, cat, await svc.creation_rules(session, viewer.campaign))
    return out


@router.get("/character-options")
async def character_options(campaign_id: str, user: UserDep, session: SessionDep, as_seat: str | None = None) -> dict:
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    return await svc.options(session, v.campaign, await campaign_catalog(session, v.campaign))


@router.post("/character-preview")
async def character_preview(
    campaign_id: str, body: PreviewIn, user: UserDep, session: SessionDep, as_seat: str | None = None
) -> dict:
    """Живой лист конструктора по правилам кампании: ничего не сохраняет."""
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    cat = await campaign_catalog(session, v.campaign)
    return svc.preview(body.model_dump(exclude_none=True), cat, await svc.creation_rules(session, v.campaign))


@router.get("/characters", response_model_exclude_unset=True)
async def list_characters(
    campaign_id: str, user: UserDep, session: SessionDep, as_seat: str | None = None
) -> list[CharacterView]:
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
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


@router.post("/characters", status_code=201, response_model_exclude_unset=True)
async def create_character(
    campaign_id: str, body: CharacterIn, user: UserDep, session: SessionDep, as_seat: str | None = None
) -> CharacterView:
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    rules = await svc.creation_rules(session, v.campaign)
    ch = await svc.create_draft(session, v, body.model_dump(exclude_none=True), rules)
    await session.commit()
    return await _view(session, v, ch)


@router.get("/characters/{character_id}", response_model_exclude_unset=True)
async def get_character(
    campaign_id: str, character_id: str, user: UserDep, session: SessionDep, as_seat: str | None = None
) -> CharacterView:
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    return await _view(session, v, await svc.get_character(session, v, character_id))


@router.put("/characters/{character_id}", response_model_exclude_unset=True)
async def update_character(
    campaign_id: str,
    character_id: str,
    body: CharacterIn,
    user: UserDep,
    session: SessionDep,
    as_seat: str | None = None,
) -> CharacterView:
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    ch = await svc.update_draft(
        session, v, await svc.get_character(session, v, character_id), body.model_dump(exclude_none=True)
    )
    await session.commit()
    return await _view(session, v, ch)


class SpellsIn(BaseModel):
    cantrips: list[str] | None = Field(None, max_length=30)
    spells: list[str] | None = Field(None, max_length=80)
    prepared: list[str] | None = Field(None, max_length=60)


@router.get("/characters/{character_id}/spells/options")
async def spell_options(
    campaign_id: str, character_id: str, user: UserDep, session: SessionDep, as_seat: str | None = None
) -> dict:
    """Что герой может выучить или подготовить: заклинания его класса до доступного круга."""
    from app.core import spells as spellbook

    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    ch = await svc.get_character(session, v, character_id)
    if not (v.seat is not None and ch.seat_id == v.seat.id) and not v.can_review:
        raise AccessDenied("чужую книгу заклинаний видит только её хозяин и мастер")
    cat = await campaign_catalog(session, v.campaign)
    return {"spells": spellbook.learnable(ch.sheet or {}, cat)}


@router.put("/characters/{character_id}/spells", response_model_exclude_unset=True)
async def update_spells(
    campaign_id: str,
    character_id: str,
    body: SpellsIn,
    user: UserDep,
    session: SessionDep,
    request: Request,
    as_seat: str | None = None,
) -> CharacterView:
    """Книга заклинаний в игре: выучить открывшееся с уровнем, сменить подготовленные после отдыха."""
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    ch = await svc.get_character(session, v, character_id)
    cat = await campaign_catalog(session, v.campaign)
    await svc.update_spells(session, v, ch, cat, body.model_dump(exclude_none=True))
    await session.commit()
    view = await _view(session, v, ch)
    if ch.seat_id:
        await request.app.state.bus.publish(
            campaign_id, envelope("character.sheet", campaign_id, {"character": view}), [ch.seat_id]
        )
    return view


@router.post("/characters/{character_id}/roll-abilities")
async def roll_abilities(
    campaign_id: str,
    character_id: str,
    user: UserDep,
    session: SessionDep,
    request: Request,
    as_seat: str | None = None,
):
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    ch = await svc.get_character(session, v, character_id)
    totals = await svc.roll_abilities(session, v, ch, request.app.state.dice_factory())
    await session.commit()
    return {"rolls": totals}


@router.post("/characters/{character_id}/submit")
async def submit(
    campaign_id: str,
    character_id: str,
    user: UserDep,
    session: SessionDep,
    request: Request,
    as_seat: str | None = None,
) -> dict:
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
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


@router.post("/characters/{character_id}/review", response_model_exclude_unset=True)
async def review(
    campaign_id: str,
    character_id: str,
    body: ReviewIn,
    user: UserDep,
    session: SessionDep,
    request: Request,
    as_seat: str | None = None,
) -> CharacterView:
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
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
    campaign_id: str,
    character_id: str,
    user: UserDep,
    session: SessionDep,
    request: Request,
    as_seat: str | None = None,
) -> dict:
    """Ещё раз отдать героя на проверку ИИ-мастеру, например после смены модели."""
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
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


@router.post("/premades", status_code=201, response_model_exclude_unset=True)
async def create_premade(
    campaign_id: str, body: CharacterIn, user: UserDep, session: SessionDep, as_seat: str | None = None
) -> CharacterView:
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    rules = await svc.creation_rules(session, v.campaign)
    ch = await svc.create_premade(session, v, body.model_dump(exclude_none=True), rules)
    await session.commit()
    return await _view(session, v, ch)


@router.put("/premades/{character_id}", response_model_exclude_unset=True)
async def update_premade(
    campaign_id: str,
    character_id: str,
    body: CharacterIn,
    user: UserDep,
    session: SessionDep,
    as_seat: str | None = None,
) -> CharacterView:
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    ch = await svc.get_character(session, v, character_id)
    await svc.update_premade(session, v, ch, body.model_dump(exclude_none=True))
    await session.commit()
    return await _view(session, v, ch)


@router.delete("/premades/{character_id}", status_code=204)
async def delete_premade(
    campaign_id: str, character_id: str, user: UserDep, session: SessionDep, as_seat: str | None = None
) -> Response:
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    await svc.delete_premade(session, v, await svc.get_character(session, v, character_id))
    await session.commit()
    return Response(status_code=204)


@router.post("/characters/{character_id}/claim", response_model_exclude_unset=True)
async def claim(
    campaign_id: str,
    character_id: str,
    user: UserDep,
    session: SessionDep,
    request: Request,
    as_seat: str | None = None,
) -> CharacterView:
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    ch = await svc.get_character(session, v, character_id)
    cat = await campaign_catalog(session, v.campaign)
    await svc.claim(session, v, ch, cat, await svc.creation_rules(session, v.campaign))
    await session.commit()
    await request.app.state.bus.publish(
        campaign_id, envelope("character.updated", campaign_id, {"character": svc.public_view(ch)}), None
    )
    return await _view(session, v, ch)


@router.post("/characters/from-library/{library_id}", status_code=201, response_model_exclude_unset=True)
async def from_library(
    campaign_id: str, library_id: str, user: UserDep, session: SessionDep, as_seat: str | None = None
) -> CharacterView:
    """Копия героя из профиля — черновиком в кампании. Дальше его можно поправить и отправить мастеру."""
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    lc = await lib.get_mine(session, user, library_id)
    source = await lib.Worlds(session).of(lc)
    target = await campaign_catalog(session, v.campaign)
    rules = await svc.creation_rules(session, v.campaign)
    ch = await lib.copy_to_campaign(session, v, lc, rules, source.cat, target)
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
async def get_bonds(
    campaign_id: str,
    character_id: str,
    user: UserDep,
    session: SessionDep,
    request: Request,
    as_seat: str | None = None,
):
    """Вопросы о связях. Первое открытие игроком даёт вопросы по умолчанию; ИИ-мастер с каркасом в фоне
    заменяет их своими, пока на них не ответили."""
    from app.agents import prelude

    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
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
    campaign_id: str,
    character_id: str,
    body: BondsIn,
    user: UserDep,
    session: SessionDep,
    request: Request,
    as_seat: str | None = None,
) -> dict:
    """Ответы игрока. Открытые ответы видят все за столом, личные — только игрок и мастер."""
    from app.agents import prelude

    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
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


# --- характер (этап 9б) ---


class PersonaIn(BaseModel):
    text: str = Field("", max_length=4000)
    fields: dict[str, str] = Field(default_factory=dict)
    core: list[str] | None = None


class PersonaDraftIn(BaseModel):
    """Анкета для «Помочь» и «Проверить»: можно несохранённую; без неё берётся сохранённая."""

    persona: PersonaIn | None = None


class NoteIn(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=500)
    cause: str | None = Field(None, max_length=300)
    reverted: bool | None = None


async def _persona_target(session, v: Viewer, character_id: str) -> tuple[Character, bool]:
    """Анкету видят игрок героя, мастер и владелец; правит игрок героя (владелец — за ИИ-игрока через as_seat)."""
    ch = await svc.get_character(session, v, character_id)
    mine = v.seat is not None and ch.seat_id == v.seat.id and ch.owner_user_id == v.user.id
    if not (mine or v.is_master or v.can_review or v.is_owner):
        raise AccessDenied("характер героя видят его игрок и мастер")
    if ch.status in ("retired", "premade"):
        raise Conflict("у этого героя нет анкеты характера")
    return ch, mine


async def _persona_out(session, campaign_id: str, ch: Character, mine: bool) -> dict:
    from app.core import persona

    notes = await persona.notes_of(session, campaign_id, ch.id)
    return {
        "persona": persona.normalize(ch.persona),
        "schema": persona.schema(),
        "notes": [persona.note_out(n) for n in notes],
        "can_edit": mine,
    }


@router.get("/characters/{character_id}/persona")
async def get_persona(
    campaign_id: str, character_id: str, user: UserDep, session: SessionDep, as_seat: str | None = None
):
    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    ch, mine = await _persona_target(session, v, character_id)
    return await _persona_out(session, campaign_id, ch, mine)


@router.put("/characters/{character_id}/persona")
async def put_persona(
    campaign_id: str, character_id: str, body: PersonaIn, user: UserDep, session: SessionDep, as_seat: str | None = None
):
    from app.core import persona

    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    ch, mine = await _persona_target(session, v, character_id)
    if not mine:
        raise AccessDenied("характер правит игрок героя")
    ch.persona = persona.normalize(body.model_dump())
    await session.commit()
    return await _persona_out(session, campaign_id, ch, mine)


async def _draft(session, v: Viewer, character_id: str, body: PersonaDraftIn) -> dict:
    ch, mine = await _persona_target(session, v, character_id)
    if not mine:
        raise AccessDenied("помощник и проверка — у игрока героя")
    sheet = body.persona.model_dump() if body.persona else dict(ch.persona or {})
    await session.rollback()  # модель думает долго: базу не держим
    return sheet


@router.post("/characters/{character_id}/persona/help")
async def help_persona(
    campaign_id: str,
    character_id: str,
    body: PersonaDraftIn,
    user: UserDep,
    session: SessionDep,
    request: Request,
    as_seat: str | None = None,
) -> dict:
    """«Помочь»: модель дописывает пустые поля; заполненное не трогает. Результат не сохраняется сам."""
    from app.agents import character

    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    sheet = await _draft(session, v, character_id, body)
    return {
        "persona": await character.help_fill(request.app.state.master, campaign_id, sheet, character_id=character_id)
    }


@router.post("/characters/{character_id}/persona/tables")
async def tables_persona(
    campaign_id: str,
    character_id: str,
    body: PersonaDraftIn,
    user: UserDep,
    session: SessionDep,
    as_seat: str | None = None,
) -> dict:
    """«Из таблиц пакета»: черта, идеал, привязанность и слабость — по строке в пустые места анкеты.
    Результат не сохраняется сам, как у «Помочь»."""
    import random

    from app.core import persona

    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    ch, mine = await _persona_target(session, v, character_id)
    if not mine:
        raise AccessDenied("таблицы характера — у игрока героя")
    sheet = body.persona.model_dump() if body.persona else dict(ch.persona or {})
    cat = await campaign_catalog(session, v.campaign)
    tables = [e.data for e in cat.by_kind("persona_table")]
    if not tables:
        raise Conflict("в версии пакета, на которой идёт кампания, нет таблиц характера")
    hero_ids = {x for x in ((ch.sheet or {}).get("class_id"), (ch.sheet or {}).get("origin_id")) if x}
    out, taken = persona.from_tables(sheet, tables, hero_ids, random.SystemRandom().choice)
    return {"persona": out, "taken": taken}


@router.post("/characters/{character_id}/persona/test")
async def test_persona(
    campaign_id: str,
    character_id: str,
    body: PersonaDraftIn,
    user: UserDep,
    session: SessionDep,
    request: Request,
    as_seat: str | None = None,
) -> dict:
    """«Проверить»: три пробные сцены — спор в отряде, соблазн, опасность."""
    from app.agents import character

    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    sheet = await _draft(session, v, character_id, body)
    scenes = await character.try_scenes(request.app.state.master, campaign_id, sheet, character_id=character_id)
    return {"scenes": scenes}


@router.patch("/characters/{character_id}/persona/notes/{note_id}")
async def patch_note(
    campaign_id: str,
    character_id: str,
    note_id: str,
    body: NoteIn,
    user: UserDep,
    session: SessionDep,
    as_seat: str | None = None,
) -> dict:
    """Поправить запись летописи или откатить её (и вернуть)."""
    from app.core import persona
    from app.db.models import PersonaNote

    v = await get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    ch, mine = await _persona_target(session, v, character_id)
    if not mine:
        raise AccessDenied("летопись правит игрок героя")
    n = await session.get(PersonaNote, note_id)
    if n is None or n.character_id != ch.id:
        raise Conflict("запись летописи не найдена")
    persona.edit_note(n, body.text, body.cause, body.reverted)
    await session.commit()
    return await _persona_out(session, campaign_id, ch, mine)
