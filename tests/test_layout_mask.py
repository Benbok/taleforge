# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Маска пола участка (спецификация 2026-10-12, §3.3): одна мера непроходимости для шага, пути, видимости и карты."""

from app.core import positions as grid
from app.core import reach, sketch, steps
from tests.game import import_base, party
from tests.test_map import _ok, _play
from tests.test_sketch import CELL

RING = {
    "shape": "cave",
    "cols": 5,
    "rows": 5,
    "party": [2, 2],
    "walls": [],
    "mask": ["#...#", ".....", ".....", ".....", "#...#"],
    "exits": [{"name": "Лаз", "side": "w", "at": 2, "kind": "gap", "state": "open"}],
    "features": [],
}


def test_legacy_sketch_reads_exactly_as_before():
    assert sketch.floor_cells(CELL) is None
    assert sketch.solid_cells(CELL) == {(5, 0)}
    assert sketch.exit_cells(CELL, CELL["exits"][0]) == [reach.exit_cell(CELL, CELL["exits"][0])] == [(1, 3)]
    assert sketch.check(CELL, set()) == []
    assert "mask" not in sketch.for_viewer(CELL, False, set())


def test_mask_makes_void_cells_solid():
    assert sketch.solid_cells(RING) == {(0, 0), (4, 0), (0, 4), (4, 4)}
    assert sketch.encode_mask(sketch.floor_cells(RING), 5, 5) == RING["mask"]
    assert sketch.check(RING, set()) == []
    assert sketch.for_viewer(RING, False, set())["mask"] == RING["mask"]


def test_bad_mask_and_feature_on_void_are_errors():
    assert any("маска пола" in e for e in sketch.check({**RING, "mask": ["#..#"]}, set()))
    on_void = {**RING, "features": [{"name": "Сундук", "kind": "object", "cells": [[0, 0, 0, 0]]}]}
    assert any("«Сундук» стоит на стене (0, 0)" in e for e in sketch.check(on_void, set()))
    assert any("отряд" in e for e in sketch.check({**RING, "party": [4, 4]}, set()))


def test_diagonal_between_two_void_cells_is_closed():
    pinch = {"shape": "cave", "cols": 2, "rows": 2, "party": [0, 1], "walls": [], "exits": [], "features": [],
             "mask": ["#.", ".#"]}  # fmt: skip
    assert reach.walk_region(pinch, (0, 1)) == {(0, 1)}


def test_wide_exit_occupies_interval():
    sk = {
        "shape": "open",
        "cols": 6,
        "rows": 4,
        "party": [1, 1],
        "walls": [],
        "features": [],
        "exits": [
            {"name": "Поле", "side": "e", "at": 1, "width": 2, "kind": "gap", "state": "open"},
            {"name": "Калитка", "side": "e", "at": 2, "kind": "gap", "state": "open"},
        ],
    }
    assert any("два выхода в одной клетке стороны восток" in e for e in sketch.check(sk, set()))
    assert sketch.exit_cells(sk, sk["exits"][0]) == [(5, 1), (5, 2)]
    too_wide = {**sk, "exits": [{**sk["exits"][0], "at": 3}]}
    assert any("at от 0 до 2" in e for e in sketch.check(too_wide, set()))
    stored = {**sk["exits"][0], "cells": [[4, 1], [4, 2]]}
    assert sketch.exit_cells(sk, stored) == [(4, 1), (4, 2)]


def test_hero_cannot_step_into_void_or_squeeze_between_void_corners(client, admin, settings):
    import_base(settings)
    c, _, hero = party(client, admin)
    cid, hid = c["id"], hero["id"]

    async def walk(ctx):
        place = (await _ok(ctx, "create_location", {"name": "Грот", "make_current": True}))["location_id"]
        en = ctx.world.entities[place]
        en.state = {
            **(en.state or {}),
            "sketch": {
                "shape": "cave",
                "cols": 4,
                "rows": 3,
                "party": [0, 0],
                "walls": [],
                "exits": [],
                "features": [],
                "mask": [".#..", "#...", "...."],
            },  # fmt: skip
        }
        w = ctx.world
        void = grid.cell_problem(w, place, (1, 0), hid)
        stuck = steps.path(w, place, (0, 0), (2, 1), hid)  # из (0,0) только по диагонали между пустотами
        free = steps.path(w, place, (1, 1), (3, 0), hid)
        return void, stuck, free

    void, stuck, free = _play(settings, cid, walk)
    assert "вне пола" in void
    assert stuck is None
    assert free is not None and free[-1] == (3, 0)
