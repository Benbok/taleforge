"""«Почему такое число» (ТЗ, раздел 10; документ дизайна, окно героя): разбор производной величины героя по тем же
формулам, что считает движок, и последние события журнала, которые её меняли.

Разбор видит только игрок этого героя и мастер: это его лист. Скрытые броски в историю не попадают.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import CatalogView
from app.core import rolls
from app.core.world import character_actor
from app.db.models import ActiveEffect, Character, Event, InventoryItem
from app.rules.dnd5e.character import choice_slices, hit_die, origin_bonuses
from app.rules.dnd5e.engine import Dnd5eEngine
from app.rules.dnd5e.tables import ABILITIES, SKILLS

engine = Dnd5eEngine()
HISTORY = 8
# инструменты, которые меняют хиты героя
HP_TOOLS = ("resolve_attack", "apply_hazard", "death_save", "use_item", "rest", "apply_effect", "grant_level")


class ExplainError(Exception):
    pass


def _signed(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


def _part(label: str, value: int | str, signed: bool = True) -> dict[str, Any]:
    return {"label": label, "value": _signed(value) if signed and isinstance(value, int) else str(value)}


def _inputs(ch: Character, cat: CatalogView, inventory: list[InventoryItem]):
    sheet = ch.sheet or {}
    cls = cat.find(sheet.get("class_id", ""), "class")
    origin = cat.find(sheet.get("origin_id", ""), "origin")
    items = []
    for it in inventory:
        rec = cat.find(it.item_template_id, "item_template")
        if rec is not None:
            items.append((it, {"id": rec.id, **rec.data}, it.display_name or rec.name))
    return sheet, (cls.data if cls else {}), (origin.data if origin else {}), (origin.name if origin else None), items


def explain(ch: Character, cat: CatalogView, inventory: list[InventoryItem], effects: list[ActiveEffect], stat: str):
    """Разбор величины ``stat``: ac, hp_max, initiative, speed, pb, passive_perception, ability:<str…>,
    save:<str…>, skill:<athletics…>, attack:<ключ атаки>."""
    try:
        actor = character_actor(ch, cat, inventory, effects)
    except Exception as e:  # noqa: BLE001 — незаконченный лист
        raise ExplainError("лист героя ещё не собран") from e
    sheet, cls, origin, origin_name, items = _inputs(ch, cat, inventory)
    level = int(sheet.get("level") or 1)
    mods, pb = actor.mods, actor.pb
    parts: list[dict[str, Any]] = []
    note = None
    kind, _, key = stat.partition(":")

    def ability_part(a: str) -> dict[str, Any]:
        return _part(f"{rolls.ABILITY_RU[a]} {actor.abilities[a]}", mods[a])

    if stat == "ac":
        label, value = "Класс доспеха", actor.ac
        armor = next((x for it, x, _ in items if it.equipped and x.get("category") == "armor"
                      and x.get("armor_type") != "shield"), None)  # fmt: skip
        armor_name = next((n for it, x, n in items if x is armor), None)
        if armor is None:
            parts += [_part("Без доспеха", 10, signed=False), ability_part("dex")]
        else:
            parts.append(_part(armor_name or "Доспех", int(armor["ac_base"]), signed=False))
            cap = armor.get("dex_cap")
            dex = mods["dex"] if cap is None else min(mods["dex"], cap)
            if cap == 0:
                note = "Тяжёлый доспех: Ловкость не добавляется."
            else:
                parts.append(_part(f"Ловкость{f' (не больше {cap})' if cap is not None else ''}", dex))
        for it, x, n in items:
            if it.equipped and x.get("armor_type") == "shield":
                parts.append(_part(n, int(x.get("ac_bonus", 2))))
        for src, m in actor.modifiers.own("add"):
            if m.get("target") == "ac" and isinstance(m.get("value"), int):
                rec = cat.find(src)
                parts.append(_part(rec.name if rec else src, m["value"]))
    elif stat == "hp_max":
        hd = hit_die(cls)
        label, value = "Максимум хитов", actor.hp.maximum
        parts.append(_part(f"1-й уровень: кость d{hd}", hd, signed=False))
        parts.append(_part(f"Телосложение × {level}", mods["con"] * level))
        if level > 1:
            parts.append(_part(f"уровни 2–{level}: по {hd // 2 + 1} (среднее d{hd})", (hd // 2 + 1) * (level - 1)))
        note = "Каждый уровень даёт не меньше 1 хита."
    elif stat == "initiative":
        label, value = "Инициатива", mods["dex"]
        parts.append(ability_part("dex"))
    elif stat == "speed":
        label, value = "Скорость", int(origin.get("speed") or 30)
        parts.append(_part(origin_name or "Происхождение", f"{value} фт", signed=False))
    elif stat == "pb":
        label, value = "Бонус мастерства", pb
        parts.append(_part(f"{level} уровень", pb))
        note = "Растёт на 1 на 5, 9, 13 и 17 уровнях."
    elif stat == "passive_perception":
        label, value = "Пассивная внимательность", 10 + actor.skills["perception"]
        parts += [_part("База", 10, signed=False), _part("Внимательность", actor.skills["perception"])]
    elif kind == "ability" and key in ABILITIES:
        label, value = rolls.ABILITY_RU[key], actor.abilities[key]
        parts.append(_part("Распределено при создании", int((sheet.get("abilities") or {}).get(key, 10)), signed=False))
        fixed, groups = origin_bonuses(origin)
        if fixed.get(key):
            parts.append(_part(origin_name or "Происхождение", fixed[key]))
        picked = sum((g["bonus"] for g, p in zip(groups, choice_slices(sheet, groups), strict=True) if key in p), 0)
        if picked:
            parts.append(_part(f"{origin_name or 'Происхождение'}: на выбор", picked))
        if value < sum(int(p["value"]) for p in parts):
            note = "Выше 20 характеристика не поднимается."
        note = (note + " " if note else "") + f"Модификатор {_signed(mods[key])}: (значение − 10) / 2 вниз."
    elif kind == "save" and key in ABILITIES:
        label, value = f"Спасбросок: {rolls.ABILITY_RU[key]}", actor.saves[key]
        parts.append(ability_part(key))
        if key in (cls.get("saving_throws") or []):
            parts.append(_part("Владение (класс)", pb))
    elif kind == "skill" and key in SKILLS:
        a = SKILLS[key]
        label, value = rolls.SKILL_RU.get(key, key), actor.skills[key]
        parts.append(ability_part(a))
        origin_skills = ((origin.get("proficiencies") or {}).get("skills")) or []
        if key in (sheet.get("skills") or []):
            parts.append(_part("Владение (выбор класса)", pb))
        elif key in origin_skills:
            parts.append(_part(f"Владение ({origin_name or 'происхождение'})", pb))
    elif kind == "attack":
        atk = next((x for x in actor.attacks if x["key"] == key), None)
        if atk is None:
            raise ExplainError("нет такой атаки")
        label, value = f"Атака: {atk['name']}", atk["attack_bonus"]
        item = next((x for _, x, _ in items if x["id"] == key), None)
        props = (item or {}).get("properties") or []
        ranged = (item or {}).get("weapon_group", "").endswith("ranged")
        if item is None:
            used = "str"
        elif "finesse" in props:
            used = "dex" if mods["dex"] > mods["str"] else "str"
        else:
            used = "dex" if ranged else "str"
        parts.append(ability_part(used))
        if atk["attack_bonus"] - mods[used]:
            parts.append(_part("Владение оружием", atk["attack_bonus"] - mods[used]))
        note = f"Урон {atk['damage']} ({rolls.DAMAGE_RU.get(atk['damage_type'], atk['damage_type'])})."
        if "finesse" in props:
            note += " Фехтовальное: берётся лучшая из Силы и Ловкости."
    else:
        raise ExplainError(f"не знаю, как разобрать «{stat}»")
    return {"stat": stat, "label": label, "value": value, "parts": parts, "note": note}


async def hp_history(session: AsyncSession, ch: Character) -> list[str]:
    """Последние открытые события, которые меняли хиты героя, строками карточек бросков."""
    q = (
        select(Event)
        .where(
            Event.campaign_id == ch.campaign_id,
            Event.target_id == ch.id,
            Event.tool.in_(HP_TOOLS),
            Event.hidden.is_(False),
        )
        .order_by(Event.created_at.desc())
        .limit(HISTORY)
    )
    out = []
    for ev in (await session.scalars(q)).all():
        c = rolls.card(ev, {ch.id})
        out.append(rolls.line(c) if c else ev.tool)
    return list(reversed(out))


async def explain_for(session: AsyncSession, ch: Character, cat: CatalogView, stat: str) -> dict[str, Any]:
    inv = (await session.scalars(select(InventoryItem).where(InventoryItem.character_id == ch.id))).all()
    eff = (await session.scalars(select(ActiveEffect).where(ActiveEffect.target_id == ch.id))).all()
    if stat == "hp":
        res = ch.resources or {}
        return {
            "stat": "hp",
            "label": "Хиты",
            "value": res.get("hp"),
            "parts": [_part("Максимум", res.get("hp_max"), signed=False)]
            + ([_part("Временные хиты", res["temp_hp"])] if res.get("temp_hp") else []),
            "note": "При 0 хитов — спасброски от смерти.",
            "history": await hp_history(session, ch),
        }
    return explain(ch, cat, list(inv), list(eff), stat)
