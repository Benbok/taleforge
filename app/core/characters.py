"""Создание персонажа (ТЗ, раздел 5.1): черновик в конструкторе, проверка правил сервером, проверка мастером.

Статусы: draft → submitted → approved (в игре) → dead | retired. Броски 4d6 сервер делает один раз и пишет
в журнал. При одобрении персонаж получает стартовое снаряжение класса и полные хиты.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import CatalogView
from app.core.campaigns import AccessDenied, Conflict, NotFound, Viewer
from app.core.world import character_actor, get_scene
from app.db.models import Campaign, CampaignSecret, Character, ContentPack, Event, InventoryItem, as_utc
from app.rules.dice import Dice
from app.rules.dnd5e.character import (
    ABILITY_METHODS,
    creation_options,
    roll_ability_scores,
    starting_items,
    validate_character,
)

DEFAULT_RULES = {
    "methods": ["builder"],  # способ создания: свой (builder); готовые варианты — позже
    "ability_methods": ["standard_array", "point_buy", "roll"],
    "start_level": 1,
    "review": "master",  # master — обязательная проверка мастером; auto — одобрение после проверки правил
}
ACTIVE = ("draft", "submitted", "approved", "active")
SHEET_FIELDS = (
    "class_id",
    "origin_id",
    "ability_method",
    "abilities",
    "ability_choice",
    "skills",
    "equipment_choices",
)


async def creation_rules(session: AsyncSession, campaign: Campaign) -> dict:
    rules = {**DEFAULT_RULES, **((campaign.settings or {}).get("creation_rules") or {})}
    cap = 20
    for pid, ver in campaign.content_chain or []:
        pack = await session.get(ContentPack, (pid, ver))
        if pack and pack.manifest.get("level_cap"):
            cap = min(cap, int(pack.manifest["level_cap"]))
    rules["level_cap"] = cap
    rules["ability_methods"] = [m for m in rules["ability_methods"] if m in ABILITY_METHODS]
    return rules


def _items(cat: CatalogView) -> dict[str, dict]:
    return {e.id: {"id": e.id, **e.data} for e in cat.by_kind("item_template")}


async def options(session: AsyncSession, campaign: Campaign, cat: CatalogView) -> dict:
    return await options_for_rules(await creation_rules(session, campaign), cat)


async def options_for_rules(rules: dict, cat: CatalogView) -> dict:
    items = _items(cat)
    classes = []
    for e in cat.by_kind("class"):
        d = e.data
        se = d.get("starting_equipment") or {}
        choices = []
        for alternatives in (se.get("choices") or []) if isinstance(se, dict) else []:
            opts = []
            for alt in alternatives:
                bundle = alt if isinstance(alt, list) else [alt]
                parts = []
                for x in bundle:
                    if "item" in x:
                        parts.append({**x, "name": items.get(x["item"], {}).get("name", x["item"])})
                    else:
                        parts.append(x)
                opts.append(parts)
            choices.append(opts)
        classes.append(
            {
                "id": e.id,
                "name": e.name,
                "description": d.get("description", ""),
                "hit_die": d.get("hit_die"),
                "saving_throws": d.get("saving_throws", []),
                "skills_choose": d.get("skills_choose", {}),
                "proficiencies": d.get("proficiencies", {}),
                "equipment_fixed": (se.get("fixed") or []) if isinstance(se, dict) else [],
                "equipment_choices": choices,
            }
        )
    origins = [
        {
            "id": e.id,
            "name": e.name,
            "description": e.data.get("description", ""),
            "ability_bonuses": e.data.get("ability_bonuses", {}),
            "ability_choose": e.data.get("ability_choose"),
            "speed": e.data.get("speed"),
            "features": [f.get("name") for f in e.data.get("features") or [] if isinstance(f, dict)],
        }
        for e in cat.by_kind("origin")
    ]
    weapons = {
        e.id: {"name": e.name, "group": e.data.get("weapon_group")}
        for e in cat.by_kind("item_template")
        if e.data.get("category") == "weapon" and e.data.get("weapon_group") != "improvised"
    }
    return {**creation_options(classes, origins, rules), "rules": rules, "weapons": weapons}


def errors_for(ch: Character, cat: CatalogView, rules: dict) -> list[str]:
    sheet = ch.sheet or {}
    cls = cat.find(sheet.get("class_id") or "", "class")
    origin = cat.find(sheet.get("origin_id") or "", "origin")
    errs = validate_character(sheet, cls.data if cls else None, origin.data if origin else None, rules, _items(cat))
    if not ch.name.strip():
        errs.append("нужно имя")
    return errs


def _own(viewer: Viewer, ch: Character) -> None:
    if ch.owner_user_id != viewer.user.id or viewer.seat is None or ch.seat_id != viewer.seat.id:
        raise AccessDenied("это не ваш персонаж")


async def get_character(session: AsyncSession, viewer: Viewer, character_id: str) -> Character:
    ch = await session.get(Character, character_id)
    if ch is None or ch.campaign_id != viewer.campaign.id:
        raise NotFound("персонаж не найден")
    return ch


async def create_draft(session: AsyncSession, viewer: Viewer, data: dict[str, Any], rules: dict) -> Character:
    if not viewer.is_player:
        raise AccessDenied("персонажа создаёт игрок на своём месте")
    q = select(Character).where(Character.seat_id == viewer.seat.id, Character.status.in_(ACTIVE))
    if (await session.scalars(q)).first() is not None:
        raise Conflict("у этого места уже есть персонаж")
    ch = Character(
        campaign_id=viewer.campaign.id,
        seat_id=viewer.seat.id,
        owner_user_id=viewer.user.id,
        name=str(data.get("name") or "").strip()[:64],
        status="draft",
        sheet={"level": int(rules.get("start_level") or 1)},
    )
    _apply(ch, data)
    session.add(ch)
    await session.flush()
    return ch


def _apply(ch: Character, data: dict[str, Any]) -> None:
    sheet = dict(ch.sheet or {})
    for k in SHEET_FIELDS:
        if k in data and data[k] is not None:
            sheet[k] = data[k]
    ch.sheet = sheet
    for k in ("public_bio", "private_backstory"):
        if data.get(k) is not None:
            setattr(ch, k, str(data[k])[:4000])
    if data.get("personality") is not None:
        ch.personality = dict(data["personality"])
    if data.get("name") is not None:
        ch.name = str(data["name"]).strip()[:64]


async def update_draft(session: AsyncSession, viewer: Viewer, ch: Character, data: dict[str, Any]) -> Character:
    _own(viewer, ch)
    if ch.status not in ("draft", "approved", "active"):
        raise Conflict("персонаж на проверке или выбыл: менять нельзя")
    if ch.status != "draft":
        # в игре имя, внешность и история меняются сразу, механика — только в конструкторе (раздел 5.1)
        data = {k: v for k, v in data.items() if k in ("name", "public_bio", "private_backstory", "personality")}
    _apply(ch, data)
    await session.flush()
    return ch


async def roll_abilities(session: AsyncSession, viewer: Viewer, ch: Character, dice: Dice) -> list[int]:
    """4d6 без меньшего, один раз на персонажа: результат и кубики — в журнал."""
    _own(viewer, ch)
    if ch.status != "draft":
        raise Conflict("броски — только в черновике")
    if (ch.sheet or {}).get("ability_rolls"):
        raise Conflict("характеристики уже брошены: перебрасывать нельзя")
    totals, rolls = roll_ability_scores(dice)
    ch.sheet = {**(ch.sheet or {}), "ability_method": "roll", "ability_rolls": totals}
    session.add(
        Event(
            campaign_id=ch.campaign_id,
            tool="roll_ability_scores",
            actor_id=ch.id,
            target_id=ch.id,
            payload={"totals": totals},
            dice=[
                {"expr": "4d6kh3", "rolls": [[6, v] for v in r], "total": t} for r, t in zip(rolls, totals, strict=True)
            ],
        )
    )
    await session.flush()
    return totals


async def submit(session: AsyncSession, viewer: Viewer, ch: Character, cat: CatalogView, rules: dict) -> list[str]:
    _own(viewer, ch)
    if ch.status != "draft":
        raise Conflict("отправить на проверку можно только черновик")
    errs = errors_for(ch, cat, rules)
    if errs:
        return errs
    ch.status = "submitted"
    ch.review_comment = None
    if rules.get("review") == "auto":
        await approve_character(session, viewer.campaign, ch, cat)
    await session.flush()
    return []


async def approve_character(session: AsyncSession, campaign: Campaign, ch: Character, cat: CatalogView) -> None:
    """Одобрение: стартовое снаряжение класса (если его ещё нет), полные хиты и кости хитов, место в сцене."""
    sheet = ch.sheet or {}
    cls = cat.find(sheet.get("class_id") or "", "class")
    have = (await session.scalars(select(InventoryItem).where(InventoryItem.character_id == ch.id))).all()
    if not have and cls is not None:
        items, _ = starting_items(cls.data, sheet.get("equipment_choices") or [], _items(cat))
        rows = []
        armor_done = shield_done = False  # надеть первый доспех и первый щит
        for it in items:
            rec = cat.find(it["item"])
            row = InventoryItem(character_id=ch.id, item_template_id=it["item"], qty=it["qty"])
            if rec is not None and rec.data.get("category") == "armor":
                if rec.data.get("armor_type") == "shield" and not shield_done:
                    row.equipped = shield_done = True
                elif rec.data.get("armor_type") != "shield" and not armor_done:
                    row.equipped = armor_done = True
            session.add(row)
            rows.append(row)
        await session.flush()
        have = rows
    ch.status = "approved"
    actor = character_actor(ch, cat, list(have), [])
    level = int(sheet.get("level") or 1)
    ch.resources = {
        **(ch.resources or {}),
        "hp": actor.hp.maximum,
        "hp_max": actor.hp.maximum,
        "temp_hp": 0,
        "hit_dice": level,
        "death_saves": [0, 0],
        "dead": False,
    }
    scene = await get_scene(session, campaign.id)
    ch.location_id = scene.location_id
    await session.flush()


async def review(session: AsyncSession, viewer: Viewer, ch: Character, cat: CatalogView, approve: bool, comment: str):
    """Проверка человеком: мастером или, когда мастер — ИИ, владельцем кампании."""
    if not viewer.can_review:
        raise AccessDenied("проверяет мастер")
    if ch.status != "submitted":
        raise Conflict("персонаж не на проверке")
    if not approve and not comment:
        raise Conflict("при возврате на доработку нужен комментарий")
    if approve:
        await approve_character(session, viewer.campaign, ch, cat)
    else:
        ch.status = "draft"
    ch.review_comment = comment or None
    session.add(
        Event(
            campaign_id=ch.campaign_id,
            tool="review_character",
            target_id=ch.id,
            payload={"approve": approve, "comment": comment},
        )
    )
    await session.flush()


# --- готовые герои от владельца (раздел 5.1, «готовые варианты») ---


def _can_prepare(viewer: Viewer) -> None:
    if not (viewer.is_owner or viewer.is_master):
        raise AccessDenied("готовых героев заготавливает владелец или мастер")


async def create_premade(session: AsyncSession, viewer: Viewer, data: dict[str, Any], rules: dict) -> Character:
    """Заготовка без игрока: её выберет игрок при входе в кампанию."""
    _can_prepare(viewer)
    ch = Character(
        campaign_id=viewer.campaign.id,
        seat_id=None,
        owner_user_id=None,
        name="",
        status="premade",
        creation_method="pregen",
        sheet={"level": int(rules.get("start_level") or 1)},
    )
    _apply(ch, data)
    session.add(ch)
    await session.flush()
    return ch


async def update_premade(session: AsyncSession, viewer: Viewer, ch: Character, data: dict[str, Any]) -> Character:
    _can_prepare(viewer)
    if ch.status != "premade":
        raise Conflict("героя уже выбрали: менять его может только игрок")
    _apply(ch, data)
    await session.flush()
    return ch


async def delete_premade(session: AsyncSession, viewer: Viewer, ch: Character) -> None:
    _can_prepare(viewer)
    if ch.status != "premade":
        raise Conflict("героя уже выбрали: удалить нельзя")
    await session.delete(ch)
    await session.flush()


async def claim(session: AsyncSession, viewer: Viewer, ch: Character, cat: CatalogView, rules: dict) -> Character:
    """Игрок берёт готового героя: он сразу в игре — его уже собрал и проверил владелец."""
    if not viewer.is_player:
        raise AccessDenied("выбрать героя может игрок на своём месте")
    if ch.status != "premade":
        raise Conflict("этого героя уже выбрали")
    q = select(Character).where(Character.seat_id == viewer.seat.id, Character.status.in_(ACTIVE))
    mine = (await session.scalars(q)).first()
    if mine is not None:
        if mine.status != "draft":
            raise Conflict("у этого места уже есть персонаж")
        await session.delete(mine)  # незаконченный черновик уступает место выбранному герою
        await session.flush()
    errs = errors_for(ch, cat, rules)
    if errs:
        raise Conflict("заготовка собрана не по правилам кампании: " + "; ".join(errs))
    ch.seat_id, ch.owner_user_id = viewer.seat.id, viewer.user.id
    await approve_character(session, viewer.campaign, ch, cat)
    return ch


async def record_secret_link(session: AsyncSession, campaign_id: str, ch: Character, text: str) -> None:
    """Тайная связь истории героя с сюжетом: в скрытые данные кампании, игрок её не видит."""
    secret = await session.get(CampaignSecret, campaign_id)
    plot = copy.deepcopy(secret.plot or {})
    plot.setdefault("character_links", {})[ch.id] = text
    secret.plot = plot
    await session.flush()


async def review_failure(session: AsyncSession, ch: Character) -> str | None:
    """Почему ИИ-мастер не проверил героя, если последняя попытка после отправки сорвалась."""
    if ch.status != "submitted":
        return None
    ev = (
        await session.scalars(
            select(Event)
            .where(Event.campaign_id == ch.campaign_id, Event.target_id == ch.id, Event.tool == "review_failed")
            .order_by(Event.created_at.desc())
            .limit(1)
        )
    ).first()
    if ev is None or (ch.updated_at and as_utc(ev.created_at) < as_utc(ch.updated_at)):
        return None
    return (ev.payload or {}).get("error") or "неизвестная ошибка"


def public_view(ch: Character) -> dict:
    res = ch.resources or {}
    return {
        "id": ch.id,
        "name": ch.name,
        "seat_id": ch.seat_id,
        "status": ch.status,
        "public_bio": ch.public_bio,
        "class_id": (ch.sheet or {}).get("class_id"),
        "origin_id": (ch.sheet or {}).get("origin_id"),
        "level": (ch.sheet or {}).get("level", 1),
        "hp": res.get("hp"),
        "hp_max": res.get("hp_max"),
        "dead": bool(res.get("dead")),
    }


def full_view(ch: Character, cat: CatalogView, inventory: list[InventoryItem], effects: list) -> dict:
    out = {
        **public_view(ch),
        "sheet": ch.sheet,
        "resources": ch.resources,
        "private_backstory": ch.private_backstory,
        "personality": ch.personality,
        "review_comment": ch.review_comment,
    }
    if ch.status in ("approved", "active", "dead") or (ch.sheet or {}).get("class_id"):
        try:
            a = character_actor(ch, cat, inventory, effects)
            out["derived"] = {
                "abilities": a.abilities,
                "mods": a.mods,
                "ac": a.ac,
                "hp_max": a.hp.maximum,
                "saves": a.saves,
                "skills": a.skills,
                "pb": a.pb,
                "attacks": a.attacks,
                "effects": [{"id": e.id, "template": r.id, "name": r.name, "stacks": e.stacks} for e, r in a.effects],
            }
        except Exception:  # noqa: BLE001 — незаконченный черновик: производных ещё нет
            pass
    out["inventory"] = [
        {
            "id": it.id,
            "item": it.item_template_id,
            "name": it.display_name or (cat.find(it.item_template_id).name if cat.find(it.item_template_id) else ""),
            "qty": it.qty,
            "equipped": it.equipped,
        }
        for it in inventory
    ]
    return out
