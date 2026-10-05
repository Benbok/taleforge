# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Бой на сетке по 5 футов: мастер ставит на клетку, дальность по клеткам, в начале боя все встают на свои."""

from app.core import positions
from app.tools.registry import execute
from tests.game import import_base, party
from tests.test_map import _map, _ok, _play
from tests.test_sketch import CELL


def test_cells_in_a_sketched_room(client, admin, settings):
    import_base(settings)
    c, (p1,), hero = party(client, admin)
    cid, hid = c["id"], hero["id"]

    async def fight(ctx):
        await _ok(ctx, "create_location", {"name": "Камера", "make_current": True})
        await _ok(ctx, "sketch_place", CELL)  # 6×4, отряд в (1, 2), стена (5, 0), нары (0..1, 0)
        spawn = {
            "creature_template_id": "creature.goblin",
            "name": "Гоблин",
            "cell": [4, 2],
            "count": 2,
            "attitude": "neutral",
        }
        gobs = [x["id"] for x in (await _ok(ctx, "spawn_entity", spawn))["spawned"]]
        w = ctx.world
        cells = [positions.to_master(w, w.actor_place(g), positions.pos_of(w, g).cell) for g in gobs]
        wall = await execute(ctx, "reposition", {"actor_id": hid, "cell": [5, 0]})
        bunk = await execute(ctx, "reposition", {"actor_id": hid, "cell": [0, 0]})
        taken = await execute(ctx, "reposition", {"actor_id": hid, "cell": [4, 2]})
        out = await execute(ctx, "reposition", {"actor_id": hid, "cell": [6, 2]})
        moved = await _ok(ctx, "reposition", {"actor_id": hid, "cell": [3, 2]})
        near = w.distance_ft(w.actor(hid), w.actor(gobs[0]))
        table = w.scene_table()
        return cells, wall, bunk, taken, out, moved, near, table, gobs

    cells, wall, bunk, taken, out, moved, near, table, gobs = _play(settings, cid, fight)
    assert cells[0] == (4, 2) and cells[1] != (4, 2) and max(abs(cells[1][0] - 4), abs(cells[1][1] - 2)) == 1
    assert "стена" in wall["error"]
    assert "«Нары»" in bunk["error"]
    assert "занята: там Гоблин 1" in taken["error"]
    assert "за краем места 6×4" in out["error"]
    assert moved["moved_ft"] == 10 and moved["position"]["cell"] == [2, 0]  # от строя: на 2 клетки восточнее
    assert near == 5  # соседняя клетка — вплотную
    assert "клетка (3, 2)" in table and "клетка (4, 2)" in table  # мастер видит клетки в координатах эскиза

    m = _map(client, p1, cid)
    assert m["party"][0]["cell"] == [2, 0]
    assert {tuple(x["cell"]) for x in m["around"] if x["id"] in gobs} >= {(3, 0)}


def test_grid_distance_and_zone_clears_cell(client, admin, settings):
    import_base(settings)
    c, _, hero = party(client, admin)
    cid, hid = c["id"], hero["id"]

    async def fight(ctx):
        await _ok(ctx, "create_location", {"name": "Площадь", "make_current": True})
        spawn = {"creature_template_id": "creature.goblin", "name": "Гоблин", "cell": [3, -4]}
        gob = (await _ok(ctx, "spawn_entity", spawn))["spawned"][0]["id"]
        w = ctx.world
        diag = w.distance_ft(w.actor(hid), w.actor(gob))  # герой без клетки — в строю (0, 0)
        zone = w.entities[gob].zone
        await _ok(ctx, "update_entity", {"entity_id": gob, "zone": "far"})
        return diag, zone, positions.pos_of(w, gob).cell

    diag, zone, cell = _play(settings, cid, fight)
    assert diag == 20  # по сетке SRD диагональ тоже 5 футов: max(3, 4) клетки
    assert zone == "near"
    assert cell is None  # зона заменила точную клетку


def test_combat_start_puts_everyone_on_a_cell(client, admin, settings):
    import_base(settings)
    c, _, hero = party(client, admin)
    cid, hid = c["id"], hero["id"]

    async def fight(ctx):
        await _ok(ctx, "create_location", {"name": "Площадь", "make_current": True})
        for name, bearing, att in (("Гоблин", "n", "hostile"), ("Гоблин-лучник", None, "neutral")):
            spawn = {
                "creature_template_id": "creature.goblin",
                "name": name,
                "zone": "melee",
                "bearing": bearing,
                "attitude": att,
            }
            await _ok(ctx, "spawn_entity", spawn)
        foes = [e.id for e in ctx.world.entities.values() if e.kind == "creature"]
        r = await _ok(ctx, "set_scene_mode", {"mode": "combat", "participants": [hid, *foes]})
        w = ctx.world
        ids = [x["id"] for x in w.scene.turn_order]
        return r, {i: positions.pos_of(w, i).cell for i in ids}

    r, cells = _play(settings, cid, fight)
    assert all(v is not None for v in cells.values())
    assert len(set(cells.values())) == len(cells)  # никто не делит клетку
    assert cells[hid] == (0, 0)
    assert "встали на клетки" in r["placed"]
