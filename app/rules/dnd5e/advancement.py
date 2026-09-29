"""Рост персонажа по опыту (SRD 5.1, «Character Advancement»): порог опыта для каждого уровня.

This work includes material taken from the System Reference Document 5.1 ("SRD 5.1")
by Wizards of the Coast LLC, licensed under CC BY 4.0.
"""

from __future__ import annotations

from typing import Any

# сколько опыта нужно, чтобы достичь уровня
XP_FOR_LEVEL: dict[int, int] = {
    1: 0,
    2: 300,
    3: 900,
    4: 2700,
    5: 6500,
    6: 14000,
    7: 23000,
    8: 34000,
    9: 48000,
    10: 64000,
    11: 85000,
    12: 100000,
    13: 120000,
    14: 140000,
    15: 165000,
    16: 195000,
    17: 225000,
    18: 265000,
    19: 305000,
    20: 355000,
}


def level_of(sheet: dict | None) -> int:
    return max(1, min(20, int((sheet or {}).get("level") or 1)))


def xp_of(sheet: dict | None) -> int:
    """Опыт героя. У героя без записи опыта (создан раньше или сразу на высоком уровне) — порог его уровня."""
    sheet = sheet or {}
    if sheet.get("xp") is None:
        return XP_FOR_LEVEL[level_of(sheet)]
    return int(sheet["xp"])


def next_level_xp(level: int) -> int | None:
    return XP_FOR_LEVEL.get(level + 1)


def progress_view(sheet: dict | None) -> dict[str, Any]:
    """Опыт для листа героя: сколько есть, порог текущего и следующего уровня (None — выше расти некуда)."""
    level = level_of(sheet)
    return {"xp": xp_of(sheet), "level_xp": XP_FOR_LEVEL[level], "next_xp": next_level_xp(level)}
