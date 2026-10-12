"""Общие blueprint для тестов комплекса (спецификация 2026-10-12): две комнаты за дверью и два поля со стыком."""

from __future__ import annotations

from app.core.layout.contracts import Area, Blueprint, Detail, End, Passage


def two_rooms(**over) -> Blueprint:
    """Зал 6×4 с колонной и келья 4×4 к востоку за закрытой дверью; ворота зала ведут наружу."""
    hall = Area(
        "hall", "entry", "Зал", "Зал", "indoor", "rect", 6, 4, (0, 0),
        details=(Detail("pillar", "Колонна", "cover", ((2, 1, 2, 1),), solid=True),),
    )  # fmt: skip
    cell = Area("cell", "room", "Келья", "Келья", "indoor", "rect", 4, 4, (6, 0))
    door = Passage("p_cell", "door", "Дверь кельи", "Дверь", (End("hall", "e", 2, 1), End("cell", "w", 2, 1)), "closed")
    gate = Passage("in_hall_w", "door", "Ворота", "Ворота", (End("hall", "w", 1, 1), End(place_id="en_outside")))
    return Blueprint(**{"seed": 7, "entry": "hall", "areas": (hall, cell), "passages": (door, gate), **over})
