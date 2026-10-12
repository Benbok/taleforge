"""Общие blueprint для тестов комплекса (спецификация 2026-10-12): две комнаты за дверью и два поля со стыком."""

from __future__ import annotations

from app.core.layout.contracts import Area, Blueprint, Detail, Edge, End, Passage, Terrain


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


def two_fields(stream_shift: int = 0) -> Blueprint:
    """Два поля 6×6 со свободным краем между ними; дорога и ручей пересекают стык, дорога уходит в деревню."""
    west = Area(
        "west", "field", "Западное поле", "Поле", "outdoor", "open", 6, 6, (0, 0), material="grass",
        terrain=(Terrain("road", ((0, 2, 5, 3),)), Terrain("stream", ((0, 5, 5, 5),))),
        edges=(Edge("n", 0, 6, "obstacle"), Edge("e", 0, 6, "continuation"), Edge("s", 0, 6, "obstacle"),
               Edge("w", 0, 2, "obstacle"), Edge("w", 2, 2, "boundary"), Edge("w", 4, 2, "obstacle")),
    )  # fmt: skip
    row = 5 - stream_shift
    east = Area(
        "east", "field", "Восточное поле", "Луг", "outdoor", "open", 6, 6, (6, 0), material="grass",
        terrain=(Terrain("road", ((0, 2, 5, 3),)), Terrain("stream", ((0, row, 5, row),))),
        edges=(Edge("n", 0, 6, "obstacle"), Edge("e", 0, 6, "obstacle"), Edge("s", 0, 6, "obstacle"),
               Edge("w", 0, 6, "continuation")),
    )  # fmt: skip
    edge = Passage("p_east", "edge", "Луг", "Луг", (End("west", "e", 0, 6), End("east", "w", 0, 6)))
    road = Passage("in_west_w", "edge", "Дорога", "Дорога", (End("west", "w", 2, 2), End(place_id="en_village")))
    return Blueprint(seed=3, entry="west", areas=(west, east), passages=(edge, road))
