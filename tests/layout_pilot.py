"""Общие blueprint для тестов комплекса (спецификация 2026-10-12): две комнаты за дверью и два поля со стыком."""

from __future__ import annotations

from app.core.layout.contracts import Area, Blueprint, Detail, Edge, End, Passage, Terrain
from app.core.layout.intent import LayoutIntent


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


def pilot_intent(outside_id: str = "en_village") -> LayoutIntent:
    """Пилот спецификации: поле с дорогой, ручьём и мостом у храма из шести помещений (крипта — уровнем ниже)."""
    pillars = [(1, 2), (6, 2), (1, 6), (6, 6)]
    nave_details = [
        {"detail_ref": f"pillar{i}", "name": "Колонна", "kind": "cover", "cells": [[c, r, c, r]], "solid": True}
        for i, (c, r) in enumerate(pillars)
    ] + [{"detail_ref": "altar", "name": "Алтарь", "kind": "furniture", "cells": [[3, 0, 4, 0]]}]
    return LayoutIntent.model_validate({
        "entry": "road",
        "parts": [
            {"part_ref": "road", "role": "field", "name": "Дорога у храма", "public_name": "Дорога у храма",
             "environment": "outdoor", "shape": "open", "cols": 12, "rows": 10},
            {"part_ref": "brook", "role": "field", "name": "Луг у ручья", "public_name": "Луг",
             "environment": "outdoor", "shape": "open", "cols": 12, "rows": 10,
             "connects_to": "road", "side": "e", "passage_name": "Луг"},
            {"part_ref": "narthex", "name": "Притвор", "public_name": "Притвор", "cols": 6, "rows": 4,
             "connects_to": "road", "side": "n", "passage_name": "Двери храма", "passage_state": "closed"},
            {"part_ref": "nave", "name": "Неф", "public_name": "Главный зал", "cols": 8, "rows": 10,
             "connects_to": "narthex", "side": "n", "passage_kind": "arch", "passage_name": "Арка",
             "details": nave_details},
            {"part_ref": "chapel", "name": "Часовня реликвии", "public_name": "Часовня", "cols": 5, "rows": 5,
             "connects_to": "nave", "side": "e", "passage_name": "Дверь часовни", "anchors": ["relic"]},
            {"part_ref": "sacristy", "name": "Ризница", "public_name": "Ризница", "cols": 4, "rows": 4,
             "connects_to": "nave", "side": "w", "passage_name": "Низкая дверь"},
            {"part_ref": "vault", "name": "Тайник", "public_name": "Тайник", "cols": 3, "rows": 3,
             "connects_to": "sacristy", "side": "n", "passage_name": "Тайная дверь", "secret": True},
            {"part_ref": "crypt", "name": "Крипта", "public_name": "Крипта", "cols": 8, "rows": 8, "level": -1,
             "connects_to": "nave", "passage_kind": "stairs", "passage_name": "Лестница вниз", "required": True},
        ],
        "approaches": [{"part_ref": "road", "side": "w", "kind": "edge", "public_name": "Дорога в деревню",
                        "outside_id": outside_id, "band": "road"}],
        "bands": [
            {"band_ref": "road", "kind": "road", "axis": "we", "at": 3, "width": 2},
            {"band_ref": "stream", "kind": "stream", "axis": "we", "at": 7},
            {"band_ref": "path", "kind": "path", "axis": "ns", "at": 6, "start": 5, "end": 10},
        ],
    })  # fmt: skip
