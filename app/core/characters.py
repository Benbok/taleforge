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
from app.core import bonds
from app.core import spells as spellbook
from app.core.campaigns import AccessDenied, Conflict, NotFound, Viewer
from app.core.features import uses_view
from app.core.world import character_actor, get_scene, lineage_features
from app.db.models import Campaign, CampaignSecret, Character, ContentPack, Event, InventoryItem, as_utc
from app.rules.dice import Dice
from app.rules.dnd5e.advancement import progress_view
from app.rules.dnd5e.character import (
    ABILITY_METHODS,
    class_skills_choose,
    creation_options,
    hit_die,
    origin_bonuses,
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
    "cantrips",  # заговоры
    "spells",  # известные заклинания; у волшебника — книга заклинаний
    "prepared",  # подготовленные на день (жрец, друид, паладин, волшебник, диагност)
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


def _card_texts(d: dict) -> dict:
    """Тексты карточки конструктора из пакета: строка под именем, метка, коротко и главные особенности."""
    return {
        "epithet": d.get("epithet") or "",
        "badge": d.get("badge") or "",
        "summary": d.get("summary") or "",
        "highlights": [h for h in d.get("highlights") or [] if isinstance(h, str) and h],
    }


async def options(session: AsyncSession, campaign: Campaign, cat: CatalogView) -> dict:
    return await options_for_rules(await creation_rules(session, campaign), cat)


async def options_for_rules(rules: dict, cat: CatalogView) -> dict:
    items = _items(cat)
    # Подклассы по классу: только те, что видны кампании (proposal — лишь в тестовых).
    subclasses: dict[str, list[dict]] = {}
    for e in cat.by_kind("subclass"):
        ref = e.data.get("class_ref")
        if ref:
            subclasses.setdefault(ref, []).append({"name": e.name, "description": e.data.get("description", "")})
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
                **_card_texts(d),
                "hit_die": hit_die(d),
                "saving_throws": d.get("saving_throws", []),
                "skills_choose": class_skills_choose(d),
                "proficiencies": d.get("proficiencies", {}),
                "spellcasting_ability": (d.get("spellcasting") or {}).get("ability"),
                "subclasses": subclasses.get(e.id, []),
                "spells": spellbook.class_options(cat, e.id, d, int(rules.get("start_level") or 1)),
                "equipment_fixed": [
                    {**x, "name": items.get(x.get("item"), {}).get("name", x.get("item"))}
                    for x in ((se.get("fixed") or []) if isinstance(se, dict) else [])
                ],
                "equipment_choices": choices,
            }
        )
    origins = [
        {
            "id": e.id,
            "name": e.name,
            "description": e.data.get("description", ""),
            **_card_texts(e.data),
            "ability_bonuses": origin_bonuses(e.data)[0],
            "ability_groups": origin_bonuses(e.data)[1],
            "ability_choose": e.data.get("ability_choose"),  # прежний клиент, до этапа 7.6
            "speed": e.data.get("speed"),
            "features": [f.get("name") for f in e.data.get("features") or [] if isinstance(f, dict)],
            "traits": [
                {"name": f.get("name"), "description": f.get("description", "")}
                for f in e.data.get("features") or []
                if isinstance(f, dict) and f.get("name")
            ],
            "size": e.data.get("size"),
            "darkvision": e.data.get("darkvision"),
            "proficiencies": e.data.get("proficiencies") or {},
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
    errs = foreign_errors(sheet, errs)
    if cls is not None and origin is not None:
        errs += spellbook.errors_for(sheet, cat)
    if not ch.name.strip():
        errs.append("нужно имя")
    return errs


FOREIGN = {"class": ("класс", "класс не выбран"), "origin": ("происхождение", "происхождение не выбрано")}


def foreign_errors(sheet: dict, errs: list[str]) -> list[str]:
    """Герой пришёл из профиля, собранный для другого мира: вместо общей ошибки называем, что именно не подходит."""
    for key, name in (sheet.get("foreign") or {}).items():
        if key not in FOREIGN or sheet.get(f"{key}_id"):
            continue
        what, generic = FOREIGN[key]
        errs = [e for e in errs if not e.startswith(generic)]
        errs.insert(0, f"{what} «{name}» не из мира этой кампании: выберите {what} этого мира")
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
    if sheet.get("foreign"):
        # замена выбрана: пометка о герое из другого мира больше не нужна
        sheet["foreign"] = {k: v for k, v in sheet["foreign"].items() if not sheet.get(f"{k}_id")}
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


def starting_rows(ch: Character, cls: dict, cat: CatalogView) -> list[InventoryItem]:
    """Стартовое снаряжение класса строками инвентаря: первый доспех и первый щит надеты."""
    items, _ = starting_items(cls, (ch.sheet or {}).get("equipment_choices") or [], _items(cat))
    rows = []
    armor_done = shield_done = False
    for it in items:
        rec = cat.find(it["item"])
        row = InventoryItem(character_id=ch.id, item_template_id=it["item"], qty=it["qty"], equipped=False)
        if rec is not None and rec.data.get("category") == "armor":
            if rec.data.get("armor_type") == "shield" and not shield_done:
                row.equipped = shield_done = True
            elif rec.data.get("armor_type") != "shield" and not armor_done:
                row.equipped = armor_done = True
        rows.append(row)
    return rows


def _name(cat: CatalogView, template_id: str) -> str:
    rec = cat.find(template_id)
    return rec.name if rec else template_id


def preview(data: dict[str, Any], cat: CatalogView, rules: dict) -> dict[str, Any]:
    """Живой лист конструктора: что получится из выбранного, со стартовым снаряжением, ничего не сохраняя.
    Ошибки правил — те же, что при отправке мастеру."""
    ch = Character(id="preview", name="", sheet={"level": int(rules.get("start_level") or 1)}, resources={})
    _apply(ch, data)
    if data.get("ability_rolls"):
        ch.sheet = {**ch.sheet, "ability_rolls": list(data["ability_rolls"])}
    out: dict[str, Any] = {"errors": errors_for(ch, cat, rules), "derived": None, "inventory": []}
    cls = cat.find(ch.sheet.get("class_id") or "", "class")
    if cls is None or not ch.sheet.get("origin_id"):
        return out
    try:
        rows = starting_rows(ch, cls.data, cat)
    except Exception:  # noqa: BLE001 — выбор снаряжения ещё не закончен
        rows = []
    try:
        a = character_actor(ch, cat, rows, [])
    except Exception:  # noqa: BLE001 — характеристики ещё не разложены
        return out
    origin = cat.find(ch.sheet.get("origin_id") or "", "origin")
    out["derived"] = {
        "abilities": a.abilities,
        "mods": a.mods,
        "ac": a.ac,
        "hp_max": a.hp.maximum,
        "saves": a.saves,
        "skills": a.skills,
        "pb": a.pb,
        "speed": int((origin.data if origin else {}).get("speed") or 30),
        "attacks": a.attacks,
    }
    caster = spellbook.caster_for(ch.sheet, cat)
    if caster is not None:
        out["derived"]["spellcasting"] = {**caster.as_dict(), "needs": spellbook.rules.needs(caster)}
    out["inventory"] = [
        {"item": r.item_template_id, "name": _name(cat, r.item_template_id), "qty": r.qty, "equipped": r.equipped}
        for r in rows
    ]
    return out


async def approve_character(session: AsyncSession, campaign: Campaign, ch: Character, cat: CatalogView) -> None:
    """Одобрение: стартовое снаряжение класса (если его ещё нет), полные хиты и кости хитов, место в сцене."""
    sheet = ch.sheet or {}
    cls = cat.find(sheet.get("class_id") or "", "class")
    have = (await session.scalars(select(InventoryItem).where(InventoryItem.character_id == ch.id))).all()
    if not have and cls is not None:
        rows = starting_rows(ch, cls.data, cat)
        session.add_all(rows)
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
        "can_prepare": True,  # заклинатель может сменить подготовленные до первого отдыха
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


async def record_secret_link(
    session: AsyncSession, campaign_id: str, ch: Character, text: str, *, ref: str | None = None
) -> None:
    """Тайная связь истории героя с сюжетом: в скрытые данные кампании, игрок её не видит. С ``ref`` она
    становится личным крючком — привязкой к узлу, NPC, злодею или месту каркаса."""
    from app.core import plot as plots

    secret = await session.get(CampaignSecret, campaign_id)
    if secret is None:
        secret = CampaignSecret(campaign_id=campaign_id)
        session.add(secret)
    plot = copy.deepcopy(secret.plot or {})
    plot.setdefault("character_links", {})[ch.id] = text
    if ref:
        try:
            plots.set_hook(plot, ch.id, ch.name, ref, text)
        except plots.PlotError as e:
            raise Conflict(str(e)) from e
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
        # спасброски от смерти бросаются открыто, как за столом: трекер видят все
        "death_saves": (res.get("death_saves") or [0, 0]) if res.get("hp") == 0 and not res.get("dead") else None,
        "bonds": bonds.public_bonds(ch),
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
            origin = cat.find((ch.sheet or {}).get("origin_id") or "", "origin")
            out["derived"] = {
                "abilities": a.abilities,
                "mods": a.mods,
                "ac": a.ac,
                "hp_max": a.hp.maximum,
                "saves": a.saves,
                "skills": a.skills,
                "pb": a.pb,
                "speed": int((origin.data if origin else {}).get("speed") or 30),
                "attacks": a.attacks,
                "effects": [{"id": e.id, "template": r.id, "name": r.name, "stacks": e.stacks} for e, r in a.effects],
            }
            out["features"] = uses_view(ch, cat, a.mods, a.pb)
        except Exception:  # noqa: BLE001 — незаконченный черновик: производных ещё нет
            pass
    lin, caste, feats = lineage_features(ch.sheet or {}, cat)
    if lin is not None:
        out["lineage"] = {
            "id": lin.id,
            "name": lin.name,
            "caste": (caste or {}).get("name"),
            "features": [f.get("name") for f in feats if f.get("name")],
        }
    out["progress"] = progress_view(ch.sheet)
    book = spellbook.book_view(ch.sheet or {}, ch.resources or {}, cat)
    if book is not None:
        out["spellbook"] = book
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


async def update_spells(session: AsyncSession, viewer: Viewer, ch: Character, cat: CatalogView, data: dict) -> None:
    """Книга заклинаний героя в игре: вне боя игрок добирает открывшиеся с уровнем заговоры и заклинания и меняет
    подготовленные после продолжительного отдыха. Выученное не забывается."""
    _own(viewer, ch)
    if ch.status not in ("approved", "active"):
        raise Conflict("книгу заклинаний меняют у героя в игре; черновик правят в конструкторе")
    scene = await get_scene(session, ch.campaign_id)
    if scene.mode == "combat":
        raise Conflict("в бою книгу заклинаний не открыть: заклинания учат и готовят вне боя")
    sheet = dict(ch.sheet or {})
    old = spellbook.rules.Choice.of(sheet)
    new = {
        k: [str(x) for x in data.get(k) or []] for k in ("cantrips", "spells", "prepared") if data.get(k) is not None
    }
    for k, label in (("cantrips", "заговоры"), ("spells", "заклинания")):
        if k in new:
            lost = [x for x in getattr(old, k) if x not in new[k]]
            if lost:
                raise Conflict(f"{label}: выученное не забывается, уберите из списка только новое")
    res = dict(ch.resources or {})
    if "prepared" in new and set(new["prepared"]) != set(old.prepared):
        dropped = [x for x in old.prepared if x not in new["prepared"]]
        if dropped and not res.get("can_prepare", True):
            raise Conflict("подготовленные меняют после продолжительного отдыха; сейчас можно только добавить")
        if dropped:
            res["can_prepare"] = False
    sheet.update(new)
    errs = spellbook.errors_for(sheet, cat, exact=False)
    if errs:
        raise Conflict("; ".join(errs))
    ch.sheet = sheet
    ch.resources = res
    session.add(
        Event(
            campaign_id=ch.campaign_id,
            tool="update_spells",
            actor_id=ch.id,
            target_id=ch.id,
            payload={k: v for k, v in new.items()},
        )
    )
    await session.flush()
