"""Умения героя с ограниченным числом использований: сколько их и сколько осталось до отдыха (SRD 5.1)."""

from __future__ import annotations

from typing import Any

from app.db.models import Character
from app.rules.dnd5e import features as cf
from app.rules.dnd5e import rest as rules


def pools_for(ch: Character, cat, mods: dict[str, int], pb: int) -> list[rules.Pool]:
    sheet = ch.sheet or {}
    cls = cat.find(sheet.get("class_id") or "", "class")
    if cls is None:
        return []
    return rules.pools(cls.data, int(sheet.get("level") or 1), pb, mods)


def spent_of(ch: Character) -> dict[str, int]:
    return {str(k): int(v) for k, v in ((ch.resources or {}).get("uses_spent") or {}).items()}


def uses_view(ch: Character, cat, mods: dict[str, int], pb: int) -> list[dict[str, Any]]:
    spent = spent_of(ch)
    return [p.as_dict(spent.get(p.key, 0)) for p in pools_for(ch, cat, mods, pb)]


def class_rows(ch: Character, cat) -> list[dict[str, Any]]:
    """Все умения класса героя на его уровне с текстом: мастер должен знать о них, даже если игрок не назвал."""
    sheet = ch.sheet or {}
    cls = cat.find(sheet.get("class_id") or "", "class")
    if cls is None:
        return []
    return cf.class_features(cls.data, int(sheet.get("level") or 1), sheet)


def wild_shape_forms(ch: Character, cat) -> list[dict[str, Any]] | None:
    """Звери, в которых друид может обернуться на своём уровне; None — у героя нет Дикого облика."""
    sheet = ch.sheet or {}
    cls = cat.find(sheet.get("class_id") or "", "class")
    level = int(sheet.get("level") or 1)
    if cls is None or not cf.has(cf.owned(cls.data, level), "wild_shape"):
        return None
    beasts = [(e.id, e.name, e.data) for e in cat.by_kind("creature_template")]
    return cf.wild_shape_forms(level, beasts)


def sheet_rows(ch: Character, cat, uses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Умения для листа игрока: русские тексты, как применить и сколько использований осталось до отдыха.
    Запас умения узнаётся по ключу: «bardic_inspiration» — у ступеней «bardic_inspiration_d6», «_d8»…"""
    alias = {"sorcery_points": "font_of_magic"}
    out = []
    for r in class_rows(ch, cat):
        row = {k: v for k, v in r.items() if k != "text"}
        for u in uses:
            if row["key"].startswith(alias.get(u["key"], u["key"])):
                row["uses"] = {k: u[k] for k in ("left", "max", "per_ru", "unit")}
                break
        out.append(row)
    return out


def scene_line(ch: Character, cat) -> str | None:
    """Строка умений героя для таблицы сцены: имена с числами, у друида — формы Дикого облика."""
    rows = class_rows(ch, cat)
    if not rows:
        return None
    line = "умения класса: " + cf.summary(rows)
    forms = wild_shape_forms(ch, cat)
    if forms:
        line += "; формы Дикого облика: " + ", ".join(f"{f['id']} {f['name']}" for f in forms)
    return line
