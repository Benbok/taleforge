"""Умения героя с ограниченным числом использований: сколько их и сколько осталось до отдыха (SRD 5.1)."""

from __future__ import annotations

from typing import Any

from app.db.models import Character
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
