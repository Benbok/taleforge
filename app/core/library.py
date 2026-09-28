"""Библиотека героев в профиле игрока (вне кампаний).

Герой собирается по базовым правилам SRD. В кампанию уходит его копия-черновик: её проверяют правила кампании
и мастер, а дальше она живёт своей жизнью. Изменения в кампании не трогают героя в профиле, и наоборот.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import CatalogView, load_catalog, resolve_chain
from app.core.campaigns import Conflict, NotFound, Viewer
from app.core.characters import DEFAULT_RULES, SHEET_FIELDS, _items, create_draft
from app.db.models import Character, LibraryCharacter, User
from app.rules.dice import Dice
from app.rules.dnd5e.character import roll_ability_scores, validate_character

LIBRARY_RULES = {**DEFAULT_RULES, "level_cap": 20}
MAX_HEROES = 30


async def base_catalog(session: AsyncSession) -> CatalogView:
    cat = await load_catalog(session, await resolve_chain(session, None))
    return cat.view(False)


def errors_for(lc: LibraryCharacter, cat: CatalogView) -> list[str]:
    sheet = lc.sheet or {}
    cls = cat.find(sheet.get("class_id") or "", "class")
    origin = cat.find(sheet.get("origin_id") or "", "origin")
    errs = validate_character(
        sheet, cls.data if cls else None, origin.data if origin else None, LIBRARY_RULES, _items(cat)
    )
    if not lc.name.strip():
        errs.append("нужно имя")
    return errs


def view(lc: LibraryCharacter, cat: CatalogView | None = None) -> dict[str, Any]:
    sheet = lc.sheet or {}
    out: dict[str, Any] = {
        "id": lc.id,
        "name": lc.name,
        "sheet": sheet,
        "class_id": sheet.get("class_id"),
        "origin_id": sheet.get("origin_id"),
        "level": sheet.get("level", 1),
        "public_bio": lc.public_bio,
        "private_backstory": lc.private_backstory,
        "personality": lc.personality,
        "updated_at": lc.updated_at.isoformat() if lc.updated_at else None,
    }
    if cat is not None:
        cls = cat.find(sheet.get("class_id") or "", "class")
        origin = cat.find(sheet.get("origin_id") or "", "origin")
        out["class_name"] = cls.name if cls else None
        out["origin_name"] = origin.name if origin else None
        out["errors"] = errors_for(lc, cat)
    return out


def _apply(lc: LibraryCharacter, data: dict[str, Any]) -> None:
    sheet = dict(lc.sheet or {})
    for k in SHEET_FIELDS:
        if data.get(k) is not None:
            sheet[k] = data[k]
    sheet["level"] = 1
    lc.sheet = sheet
    for k in ("public_bio", "private_backstory"):
        if data.get(k) is not None:
            setattr(lc, k, str(data[k])[:4000])
    if data.get("personality") is not None:
        lc.personality = dict(data["personality"])
    if data.get("name") is not None:
        lc.name = str(data["name"]).strip()[:64]


async def list_mine(session: AsyncSession, user: User) -> list[LibraryCharacter]:
    q = select(LibraryCharacter).where(LibraryCharacter.owner_user_id == user.id)
    return list((await session.scalars(q.order_by(LibraryCharacter.created_at))).all())


async def get_mine(session: AsyncSession, user: User, lib_id: str) -> LibraryCharacter:
    lc = await session.get(LibraryCharacter, lib_id)
    if lc is None or lc.owner_user_id != user.id:
        raise NotFound("герой не найден")
    return lc


async def create(session: AsyncSession, user: User, data: dict[str, Any]) -> LibraryCharacter:
    if len(await list_mine(session, user)) >= MAX_HEROES:
        raise Conflict(f"в профиле не больше {MAX_HEROES} героев")
    lc = LibraryCharacter(owner_user_id=user.id, name="", sheet={"level": 1})
    _apply(lc, data)
    session.add(lc)
    await session.flush()
    return lc


async def update(session: AsyncSession, lc: LibraryCharacter, data: dict[str, Any]) -> LibraryCharacter:
    _apply(lc, data)
    await session.flush()
    return lc


async def roll(session: AsyncSession, lc: LibraryCharacter, dice: Dice) -> list[int]:
    if (lc.sheet or {}).get("ability_rolls"):
        raise Conflict("характеристики уже брошены: перебрасывать нельзя")
    totals, _ = roll_ability_scores(dice)
    lc.sheet = {**(lc.sheet or {}), "ability_method": "roll", "ability_rolls": totals}
    await session.flush()
    return totals


async def copy_to_campaign(session: AsyncSession, viewer: Viewer, lc: LibraryCharacter, rules: dict) -> Character:
    """Черновик в кампании из героя профиля. Броски переносятся как есть: перебросить их в кампании нельзя."""
    data: dict[str, Any] = {k: v for k, v in (lc.sheet or {}).items() if k in SHEET_FIELDS}
    data.update(
        name=lc.name,
        public_bio=lc.public_bio,
        private_backstory=lc.private_backstory,
        personality=lc.personality,
    )
    ch = await create_draft(session, viewer, data, rules)
    sheet = dict(ch.sheet or {})
    if (lc.sheet or {}).get("ability_rolls"):
        sheet["ability_rolls"] = list(lc.sheet["ability_rolls"])
    sheet["source_library_id"] = lc.id
    ch.sheet = sheet
    await session.flush()
    return ch
