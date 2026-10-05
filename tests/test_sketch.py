# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Эскиз места: мастер рисует форму, выходы и предметы, игроки видят их на схеме, тайное скрыто."""

from app.core import sketch
from app.tools.registry import execute
from tests.game import import_base, party
from tests.test_map import _map, _ok, _play

CELL = {
    "shape": "room",
    "cols": 6,
    "rows": 4,
    "party": [1, 2],
    "walls": [[5, 0]],
    "exits": [
        {"name": "Дверь решётки", "side": "s", "at": 1, "kind": "bars", "state": "locked", "beyond": "коридор"},
        {"name": "Узкое окно", "side": "n", "at": 3, "kind": "window", "state": "closed", "beyond": "двор"},
        {"name": "Лаз под нарами", "side": "w", "at": 0, "kind": "gap", "hidden": True},
    ],
    "features": [
        {"name": "Нары", "kind": "furniture", "cells": [[0, 0, 1, 0]]},
        {"name": "Тайник в стене", "kind": "object", "cells": [[4, 3, 4, 3]], "hidden": True},
    ],
}


def test_master_sketches_a_cell_and_players_see_it(client, admin, settings):
    import_base(settings)
    c, (p1,), _ = party(client, admin)
    cid = c["id"]

    async def build(ctx):
        cell = (await _ok(ctx, "create_location", {"name": "Камера", "make_current": True}))["location_id"]
        before = ctx.world.scene_table()
        bad = await execute(
            ctx,
            "sketch_place",
            {**CELL, "party": [5, 0], "features": [{"name": "Стол", "cells": [[4, 2, 7, 2]]}]},
        )
        done = await _ok(ctx, "sketch_place", CELL)
        return cell, before, bad, done, ctx.world.scene_table()

    cell, before, bad, done, table = _play(settings, cid, build)
    assert "нет закрытого описания и эскиза" in before and "describe_place" in before  # напоминание описать место
    assert not bad["ok"] and "«Стол» выходит за пределы места 6×4" in bad["error"]
    assert "отряд (5, 0) стоит на стене" in bad["error"]
    assert "помещение 6×4 клеток" in done["sketch"] and "за ним коридор" in done["sketch"]
    assert "нет закрытого описания" not in table and "Лаз под нарами" in table  # тайное мастер видит

    m = _map(client, p1, cid)
    sk = m["sketch"]
    assert sk["cols"] == 6 and sk["party"] == [1, 2] and sk["walls"] == [[5, 0]]
    assert [x["name"] for x in sk["exits"]] == ["Дверь решётки", "Узкое окно"]  # лаз тайный
    assert [f["name"] for f in sk["features"]] == ["Нары"]
    assert sk["exits"][0]["beyond"] == "коридор" and sk["exits"][0]["state"] == "locked"


def test_sketch_exit_to_an_unknown_place_is_refused(client, admin, settings):
    import_base(settings)
    c, _, _ = party(client, admin)

    async def build(ctx):
        await _ok(ctx, "create_location", {"name": "Камера", "make_current": True})
        exits = [{"name": "Дверь", "side": "e", "at": 9, "to": "en_nowhere"}]
        return await execute(ctx, "sketch_place", {**CELL, "exits": exits})

    bad = _play(settings, c["id"], build)
    assert "at от 0 до 3 на стороне восток" in bad["error"] and "нет места en_nowhere" in bad["error"]


def test_book_room_gets_a_sketch_from_its_cells():
    grid = {"cols": 10, "rows": 8, "left": 0.0, "top": 0.0, "right": 1.0, "bottom": 0.8}
    mark = {"number": "1", "x": 0.2, "y": 0.3, "cells": [[0, 0, 3, 2], [0, 3, 1, 5]], "blocked": [[1, 1]]}
    east = {"number": "2", "x": 0.75, "y": 0.15}
    sk = sketch.from_book(mark, grid, [("Комната 2", "en_2", east)])
    assert (sk["cols"], sk["rows"]) == (4, 6)
    # Г-образная комната: правый нижний угол коробки — стена, колонна (1, 1) тоже
    assert [1, 1] in sk["walls"] and [3, 5] in sk["walls"] and [0, 0] not in sk["walls"]
    assert sk["exits"] == [
        {"side": "e", "at": 1, "kind": "passage", "state": "open", "name": "Комната 2", "to": "en_2"}
    ]
    assert sketch.check(sk, {"en_2"}) == []
