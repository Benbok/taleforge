"""Библиотека героев в профиле игрока (вне кампаний).

Герой собирается по базовым правилам SRD или для мира из пакета (sheet.pack_id): тогда конструктор предлагает
классы и происхождения этого мира. В кампанию уходит его копия-черновик: её проверяют правила кампании и мастер,
а дальше она живёт своей жизнью. Изменения в кампании не трогают героя в профиле, и наоборот. Класс или
происхождение, которых нет в мире кампании, в копию не переносятся: игрок выбирает замену в конструкторе.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import BASE_PACK_ID, BASE_RULES, CatalogView, load_catalog, resolve_chain
from app.content.importer import latest_version
from app.content.manifest import version_tuple
from app.core.campaigns import Conflict, NotFound, Viewer
from app.core.characters import DEFAULT_RULES, SHEET_FIELDS, _items, create_draft
from app.core.world import character_actor
from app.db.models import Campaign, Character, ContentPack, LibraryCharacter, User
from app.rules.dice import Dice
from app.rules.dnd5e.character import roll_ability_scores, validate_character

LIBRARY_RULES = {**DEFAULT_RULES, "level_cap": 20}
MAX_HEROES = 30


@dataclass(frozen=True)
class World:
    """Мир, для которого собирается герой профиля: каталог его пакета и правила конструктора."""

    pack_id: str | None
    name: str
    cat: CatalogView
    rules: dict


def _is_base(p: ContentPack) -> bool:
    return p.id == BASE_PACK_ID or p.manifest.get("provides") == BASE_RULES


async def base_catalog(session: AsyncSession) -> CatalogView:
    cat = await load_catalog(session, await resolve_chain(session, None))
    return cat.view(False)


async def worlds(session: AsyncSession) -> list[dict[str, Any]]:
    """Миры для героя профиля: базовые правила и последние версии пакетов миров."""
    latest: dict[str, ContentPack] = {}
    base_name = "Базовые правила D&D 5e"
    for p in (await session.scalars(select(ContentPack))).all():
        if _is_base(p):
            continue
        if p.id not in latest or version_tuple(p.version) > version_tuple(latest[p.id].version):
            latest[p.id] = p
    rows = sorted(latest.values(), key=lambda p: p.name)
    return [{"id": None, "name": base_name}] + [{"id": p.id, "name": p.name} for p in rows]


async def world(session: AsyncSession, pack_id: str | None) -> World:
    if not pack_id:
        return World(None, "Базовые правила D&D 5e", await base_catalog(session), LIBRARY_RULES)
    pack = await latest_version(session, pack_id)
    if pack is None or _is_base(pack):
        raise NotFound(f"мир «{pack_id}» не загружен: выберите другой или попросите админа загрузить пакет")
    cat = await load_catalog(session, await resolve_chain(session, pack))
    cap = min(20, int(pack.manifest.get("level_cap") or 20))
    return World(pack.id, pack.name, cat.view(False), {**LIBRARY_RULES, "level_cap": cap})


class Worlds:
    """Миры героев одного списка: каталог каждого пакета строится один раз."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._seen: dict[str | None, World] = {}

    async def of(self, lc: LibraryCharacter) -> World:
        pid = (lc.sheet or {}).get("pack_id")
        if pid not in self._seen:
            try:
                self._seen[pid] = await world(self.session, pid)
            except NotFound:
                # пакет мира удалён: показываем героя по базовым правилам, а не теряем его
                self._seen[pid] = await world(self.session, None)
        return self._seen[pid]


def errors_for(lc: LibraryCharacter, cat: CatalogView, rules: dict = LIBRARY_RULES) -> list[str]:
    sheet = lc.sheet or {}
    cls = cat.find(sheet.get("class_id") or "", "class")
    origin = cat.find(sheet.get("origin_id") or "", "origin")
    errs = validate_character(sheet, cls.data if cls else None, origin.data if origin else None, rules, _items(cat))
    if not lc.name.strip():
        errs.append("нужно имя")
    return errs


def view(lc: LibraryCharacter, w: World | None = None) -> dict[str, Any]:
    sheet = lc.sheet or {}
    cat = w.cat if w else None
    out: dict[str, Any] = {
        "id": lc.id,
        "name": lc.name,
        "sheet": sheet,
        "class_id": sheet.get("class_id"),
        "origin_id": sheet.get("origin_id"),
        "pack_id": sheet.get("pack_id"),
        "world_name": w.name if w else None,
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
        out["errors"] = errors_for(lc, cat, w.rules)
    return out


async def detail(session: AsyncSession, lc: LibraryCharacter, w: World) -> dict[str, Any]:
    """Карточка героя профиля: характеристики, спасброски, навыки и где играют его копии.
    Снаряжение героя профиля — выбор из стартовых наборов; предметы появятся у копии после одобрения в кампании."""
    cat = w.cat
    out = view(lc, w)
    if not out["errors"]:
        try:
            a = character_actor(Character(id=lc.id, name=lc.name, sheet=lc.sheet, resources={}), cat, [], [])
            out["derived"] = {
                "abilities": a.abilities,
                "mods": a.mods,
                "hp_max": a.hp.maximum,
                "saves": a.saves,
                "skills": a.skills,
                "pb": a.pb,
            }
        except Exception:  # noqa: BLE001 — лист без производных всё равно показываем
            pass
    q = (
        select(Character, Campaign.name)
        .join(Campaign, Campaign.id == Character.campaign_id)
        .where(
            Character.owner_user_id == lc.owner_user_id,
            Character.sheet["source_library_id"].as_string() == lc.id,
        )
        .order_by(Character.created_at)
    )
    out["copies"] = [
        {
            "campaign_id": ch.campaign_id,
            "campaign_name": name,
            "character_id": ch.id,
            "status": ch.status,
            "level": (ch.sheet or {}).get("level", 1),
        }
        for ch, name in (await session.execute(q)).all()
    ]
    return out


def _apply(lc: LibraryCharacter, data: dict[str, Any]) -> None:
    sheet = dict(lc.sheet or {})
    for k in SHEET_FIELDS:
        if data.get(k) is not None:
            sheet[k] = data[k]
    if "pack_id" in data:
        sheet["pack_id"] = data["pack_id"] or None
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


async def copy_to_campaign(
    session: AsyncSession,
    viewer: Viewer,
    lc: LibraryCharacter,
    rules: dict,
    source: CatalogView | None = None,
    target: CatalogView | None = None,
) -> Character:
    """Черновик в кампании из героя профиля. Броски переносятся как есть: перебросить их в кампании нельзя.
    Класс или происхождение, которых нет в мире кампании (target), не переносятся: их имена остаются в
    sheet.foreign, и конструктор кампании называет, что заменить."""
    data: dict[str, Any] = {k: v for k, v in (lc.sheet or {}).items() if k in SHEET_FIELDS}
    foreign: dict[str, str] = {}
    if target is not None:
        for key in ("class", "origin"):
            rid = data.get(f"{key}_id")
            if rid and target.find(rid, key) is None:
                was = source.find(rid, key) if source is not None else None
                foreign[key] = was.name if was else rid
                data.pop(f"{key}_id")
        if "class" in foreign:
            # навыки и стартовые наборы выбирались из списков прежнего класса
            data.pop("skills", None)
            data.pop("equipment_choices", None)
        if "origin" in foreign:
            data.pop("ability_choice", None)
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
    if foreign:
        sheet["foreign"] = foreign
    ch.sheet = sheet
    await session.flush()
    return ch
