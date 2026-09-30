"""Заклинания кампании: каталог заклинаний с подачей мира, заклинатель героя и его книга заклинаний.

Мир подаёт заклинания SRD по-своему записями ``spell_note`` (видны кампании по её статусу, как и прочие записи):
``renames`` — новое имя, ``flavors`` — как заклинание выглядит в мире, ``forbidden_spell_refs`` — чего героям нельзя
(9-й круг, иные планы). Числа всегда из записи заклинания. Механику считает app/rules/dnd5e/spells.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.content.catalog import CatalogView
from app.rules.dnd5e import spells as rules
from app.rules.dnd5e.character import final_abilities
from app.rules.dnd5e.spells import Caster, Choice

ABILITY_GEN = {
    "str": "Силы",
    "dex": "Ловкости",
    "con": "Телосложения",
    "int": "Интеллекта",
    "wis": "Мудрости",
    "cha": "Харизмы",
}


@dataclass
class SpellCatalog:
    spells: dict[str, dict[str, Any]]  # id → данные заклинания с подачей мира
    forbidden: set[str]
    source: dict[str, str]  # id класса → как сила выглядит в мире (spell_source)


_cache: dict[tuple[int, bool], SpellCatalog] = {}


def spell_catalog(cat: CatalogView) -> SpellCatalog:
    """Заклинания, как их видит кампания. Кешируется на каталог цепочки: пакеты неизменны в своей версии."""
    key = (id(cat.catalog), cat.allow_proposals)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    spells = {e.id: {"id": e.id, **e.data} for e in cat.by_kind("spell_template")}
    forbidden: set[str] = set()
    source: dict[str, str] = {}
    for note in cat.by_kind("spell_note"):
        d = note.data
        if d.get("applies_to") in (None, "all_player_characters"):
            forbidden |= {str(x) for x in d.get("forbidden_spell_refs") or []}
        for r in d.get("renames") or []:
            s = spells.get(r.get("spell_ref") or "")
            if s is not None and r.get("name"):
                spells[s["id"]] = {**s, "name": r["name"], "srd_name": s.get("name")}
        for sid, text in (d.get("flavors") or {}).items():
            if sid in spells and isinstance(text, str):
                spells[sid] = {**spells[sid], "flavor": text}
        if d.get("source_code") and d.get("description"):
            for cid in d.get("class_refs") or []:
                source.setdefault(str(cid), str(d["description"]))
    out = SpellCatalog(spells, forbidden, source)
    _cache[key] = out
    return out


def caster_for(sheet: dict, cat: CatalogView) -> Caster | None:
    """Заклинатель героя по его листу: класс, уровень и итоговые характеристики."""
    cls = cat.find(sheet.get("class_id") or "", "class")
    if cls is None:
        return None
    origin = cat.find(sheet.get("origin_id") or "", "origin")
    try:
        abilities = final_abilities(sheet, origin.data if origin else None)
    except (TypeError, ValueError):
        return None
    try:
        return rules.caster(cls.data, cls.id, int(sheet.get("level") or 1), abilities)
    except (TypeError, ValueError, rules.SpellError):
        return None


def class_options(cat: CatalogView, class_id: str, class_data: dict, level: int) -> dict[str, Any] | None:
    """Заклинания класса для конструктора: сколько выбрать на уровне и список с карточками (без чисел героя)."""
    probe = rules.caster(class_data, class_id, level, {a: 10 for a in ("str", "dex", "con", "int", "wis", "cha")})
    if probe is None:
        return None
    sc = spell_catalog(cat)
    ids = rules.class_list(probe, sc.spells, sc.forbidden)
    return {
        "ability": probe.ability,
        "mode": probe.mode,
        "cantrips": probe.cantrips,
        "known": probe.known if probe.mode in ("known", "spellbook") else None,
        # число подготовленных зависит от характеристики: считает живой лист, здесь — формула словами
        "prepared_rule": _prepared_rule(probe, class_data),
        "top_level": probe.top_level,
        "slots": probe.slots,
        "pact_slots": probe.pact_slots,
        "pact_level": probe.pact_level,
        "source": sc.source.get(class_id, ""),
        "spells": [rules.summary(sc.spells[i]) for i in ids if int(sc.spells[i].get("level", 0)) <= probe.top_level],
    }


def _prepared_rule(c: Caster, class_data: dict) -> str | None:
    if c.mode not in ("prepared", "spellbook"):
        return None
    div = rules._style(class_data).get("prepare_div", 1)
    lvl = "уровень" if div == 1 else "половина уровня"
    return f"модификатор {ABILITY_GEN.get(c.ability, c.ability)} + {lvl}, не меньше 1"


def errors_for(sheet: dict, cat: CatalogView, exact: bool = True) -> list[str]:
    c = caster_for(sheet, cat)
    if c is None:
        return []
    sc = spell_catalog(cat)
    return rules.validate(c, Choice.of(sheet), sc.spells, sc.forbidden, exact=exact)


def book_view(sheet: dict, resources: dict, cat: CatalogView) -> dict[str, Any] | None:
    """Книга заклинаний героя для листа: числа, ячейки, что знает и готовит, сколько ещё можно выучить."""
    c = caster_for(sheet, cat)
    if c is None:
        return None
    sc = spell_catalog(cat)
    ch = Choice.of(sheet)
    need = rules.needs(c)
    known_ids = ch.cantrips + [s for s in ch.spells if s not in ch.cantrips]
    if c.mode == "prepared":
        known_ids += [s for s in ch.prepared if s not in known_ids]
    cards = []
    for sid in known_ids:
        s = sc.spells.get(sid)
        if s is None:
            continue
        card = rules.summary(s)
        lvl = card["level"]
        card["prepared"] = lvl == 0 or c.mode == "known" or sid in ch.prepared
        cards.append(card)
    cards.sort(key=lambda x: (x["level"], x["name"] or ""))
    left = rules.slots_left(c, resources)
    conc = resources.get("concentration")
    return {
        **c.as_dict(),
        "mode_ru": rules.MODE_RU.get(c.mode, c.mode),
        "source": sc.source.get(c.class_id, ""),
        "slots_left": {str(k): v for k, v in left.items()},
        "pact_left": rules.pact_left(c, resources),
        "concentration": conc if isinstance(conc, dict) else None,
        "can_prepare": bool(resources.get("can_prepare", True)),
        "spells": cards,
        # места, которые открылись с уровнем: игрок добирает их вне боя в книге заклинаний
        "room": {
            "cantrips": max(0, need["cantrips"] - len(ch.cantrips)),
            "spells": max(0, need["spells"] - len(ch.spells)),
            "prepared": max(0, need["prepared"] - len(ch.prepared)),
        },
    }


def learnable(sheet: dict, cat: CatalogView) -> list[dict[str, Any]]:
    """Что герой может выучить или подготовить сейчас: заклинания его класса до доступного круга."""
    c = caster_for(sheet, cat)
    if c is None:
        return []
    sc = spell_catalog(cat)
    return [
        rules.summary(sc.spells[i])
        for i in rules.class_list(c, sc.spells, sc.forbidden)
        if int(sc.spells[i].get("level", 0)) <= c.top_level
    ]
