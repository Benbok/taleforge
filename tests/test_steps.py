# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Ход по клеткам: игрок нажимает клетку схемы, герой идёт туда в обход занятого; в бою — скорость, рывок и атака
по возможности при уходе из досягаемости."""

from app.core import positions
from app.tools.movement import hero_step
from app.tools.registry import ToolError
from tests.game import import_base, party
from tests.test_map import _map, _ok, _play
from tests.test_sketch import CELL
from tests.test_tools import call, play
from tests.test_ws import connect, next_of


async def _err(coro) -> str:
    try:
        await coro
    except ToolError as e:
        return str(e)
    raise AssertionError("ожидалась ошибка")


def test_step_goes_around_and_is_seen_on_the_map(client, admin, settings):
    import_base(settings)
    c, (p1,), hero = party(client, admin)
    cid, hid = c["id"], hero["id"]

    async def walk(ctx):
        await _ok(ctx, "create_location", {"name": "Камера", "make_current": True})
        await _ok(ctx, "sketch_place", CELL)  # 6×4, отряд в (1, 2), стена (5, 0), нары (0..1, 0)
        spawn = {"creature_template_id": "creature.goblin", "name": "Гоблин", "cell": [2, 2], "attitude": "neutral"}
        await _ok(ctx, "spawn_entity", spawn)
        wall = await _err(hero_step(ctx, hid, positions.to_rel(ctx.world, ctx.world.scene.location_id, [5, 0])))
        out = await hero_step(ctx, hid, (2, 0))  # за гоблином: путь его обходит
        bunk = await hero_step(ctx, hid, None, near=[(-1, -2), (0, -2)])  # «Подойти» к нарам
        return wall, out, bunk

    wall, out, bunk = _play(settings, cid, walk)
    assert "стена" in wall
    assert out["cell"] == [3, 2] and out["moved_ft"] == 10  # по диагонали в обход гоблина, не сквозь него
    assert bunk["cell"] == [2, 1] and bunk["moved_ft"] == 5  # клетка рядом с нарами, один шаг

    with connect(client, p1, cid) as (ws, _):
        ws.send_json({"type": "map.step", "payload": {"cell": [2, 0], "request_id": "r1"}})
        res = next_of(ws, "map.step.result")
        assert res["payload"]["ok"] and res["payload"]["request_id"] == "r1"
        bad = {"type": "map.step", "payload": {"cell": [9, 9], "request_id": "r2"}}
        ws.send_json(bad)
        assert "за краем места" in next_of(ws, "map.step.result")["payload"]["error"]
    assert _map(client, p1, cid)["party"][0]["cell"] == [2, 0]


def test_combat_step_speed_dash_and_opportunity_attack(client, admin, settings):
    import_base(settings)
    c, _, hero = party(client, admin)
    cid, hid = c["id"], hero["id"]

    async def setup(ctx):
        await _ok(ctx, "create_location", {"name": "Площадь", "make_current": True})
        spawn = {"creature_template_id": "creature.goblin", "name": "Гоблин", "cell": [1, 0]}
        gob = (await _ok(ctx, "spawn_entity", spawn))["spawned"][0]["id"]
        await _ok(ctx, "set_scene_mode", {"mode": "combat", "participants": [hid, gob]})
        sc = ctx.world.scene
        sc.state = {**sc.state, "turn": [x["id"] for x in sc.turn_order].index(hid)}  # сейчас ход героя
        return gob

    gob = play(settings, cid, [10, 10], setup)

    async def away(ctx):
        warn = await hero_step(ctx, hid, (-2, 0))
        done = await hero_step(ctx, hid, (-2, 0), confirm=True)
        return warn, done

    warn, done = play(settings, cid, [2], away)  # гоблин бьёт вдогонку и промахивается
    assert warn["confirm_needed"] and "атаку по возможности: Гоблин" in warn["warnings"][0]
    assert done["moved_ft"] == 10 and "бьёт вдогонку" in done["notes"][0] and done["left_ft"] == 20

    async def run(ctx):
        dash = await hero_step(ctx, hid, (-7, 0))
        ok = await hero_step(ctx, hid, (-7, 0), confirm=True)
        far = await _err(hero_step(ctx, hid, (-13, 0), confirm=True))
        again = await hero_step(ctx, hid, (-8, 0))  # реакция гоблина потрачена, рядом никого: без вопросов
        return dash, ok, far, again

    dash, ok, far, again = play(settings, cid, [], run)
    assert "рывок" in dash["warnings"][0]
    assert ok["dash"] and ok["left_ft"] == 25
    assert "осталось 25 футов" in far
    assert again["moved_ft"] == 5 and again["left_ft"] == 20

    async def not_mine(ctx):
        sc = ctx.world.scene
        sc.state = {**sc.state, "turn": [x["id"] for x in sc.turn_order].index(gob)}
        return await _err(hero_step(ctx, hid, (-9, 0)))

    assert "дождись своего хода" in play(settings, cid, [], not_mine)


def test_walls_are_full_barrier_for_steps_and_attacks(client, admin, settings):
    import_base(settings)
    c, _, hero = party(client, admin)
    cid, hid = c["id"], hero["id"]
    room = {"shape": "room", "cols": 6, "rows": 4, "party": [1, 1], "walls": [[2, 1], [1, 2], [3, 0], [3, 1], [3, 2]]}

    async def walk(ctx):
        await _ok(ctx, "create_location", {"name": "Стык", "make_current": True})
        await _ok(ctx, "sketch_place", room)
        step = await hero_step(ctx, hid, (1, 1))  # (2, 2): сквозь стык стен по диагонали нельзя, только в обход
        diag = await hero_step(ctx, hid, (2, 2))  # на (3, 3) по диагонали мимо угла одной стены — можно
        spawn = {"creature_template_id": "creature.goblin", "name": "Гоблин", "cell": [4, 1], "attitude": "neutral"}
        gob = (await _ok(ctx, "spawn_entity", spawn))["spawned"][0]["id"]
        bow = {"attacker_id": gob, "target_id": hid, "attack": "shortbow"}
        weapon = next(x for x in ctx.world.actor(gob).attacks if x["kind"] == "ranged")["key"]
        shot = await call(ctx, "resolve_attack", {**bow, "attack": weapon})
        return step, diag, shot

    step, diag, shot = _play(settings, cid, walk)
    assert step["cell"] == [2, 2] and step["moved_ft"] > 5  # стена — полная преграда (решение Arty)
    assert diag["cell"] == [3, 3] and diag["moved_ft"] == 5
    assert not shot["ok"] and "стена" in shot["error"], shot
