# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Учёт хода героя в бою (решение Arty 2026-10-05): одно действие, одно бонусное действие, шаги по скорости;
рывок добавляет скорость, отход снимает атаки по возможности."""

from app.core import combat, economy
from app.tools.movement import hero_step
from tests.game import import_base, party
from tests.test_map import _ok
from tests.test_steps import _err
from tests.test_tools import call, play


def test_hero_turn_counts_action_bonus_and_moves(client, admin, settings):
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

    async def turn(ctx):
        # воин отход бонусным действием не делает: это Хитрое действие плута
        refused = await call(ctx, "take_action", {"character_id": hid, "action": "disengage", "bonus": True})
        assert not refused["ok"] and "Хитрое действие" in refused["error"], refused
        ch = ctx.world.characters[hid]
        ch.sheet = {**ch.sheet, "class_id": "class.rogue", "level": 2}  # дальше герой — плут 2-го уровня
        ctx.world.invalidate(hid)
        weapon = next(x for x in ctx.world.actor(hid).attacks if x["kind"] == "melee")["key"]
        hit = {"attacker_id": hid, "target_id": gob, "attack": weapon}
        fresh = combat.public_turn(ctx.world)["economy"]
        first = await call(ctx, "resolve_attack", hit)
        second = await call(ctx, "resolve_attack", hit)
        dash = await call(ctx, "take_action", {"character_id": hid, "action": "dash"})
        bonus = await call(ctx, "take_action", {"character_id": hid, "action": "disengage", "bonus": True})
        again = await call(ctx, "take_action", {"character_id": hid, "action": "hide", "bonus": True})
        table = ctx.world.scene_table()
        step = await hero_step(ctx, hid, (-2, 0))  # отход: гоблин рядом, но вдогонку не бьёт
        far = await _err(hero_step(ctx, hid, (-8, 0)))  # рывок за действие уже не взять: только скорость
        rest = await hero_step(ctx, hid, (-6, 0))
        return (
            fresh,
            first,
            second,
            dash,
            bonus,
            again,
            table,
            step,
            (far, rest),
            combat.public_turn(ctx.world)["economy"],
        )

    fresh, first, second, dash, bonus, again, table, step, far, left = play(settings, cid, [1, 1], turn)
    assert fresh == {"action": True, "attacks_left": 0, "bonus": True, "move_left_ft": 30, "disengage": False}
    assert first["ok"], first
    assert not second["ok"] and "действие этого хода уже потрачено" in second["error"]
    assert not dash["ok"] and "действие этого хода уже потрачено" in dash["error"]
    assert bonus["ok"] and bonus["result"]["action"] == "отход"
    assert not again["ok"] and "бонусное действие этого хода уже потрачено" in again["error"]
    assert "Бран, ход героя: действие потрачено, бонусное действие потрачено, шагов ещё 30 фт, отход" in table
    assert "confirm_needed" not in step and step["moved_ft"] == 10 and step["left_ft"] == 20
    far, rest = far
    assert "осталось 20 футов" in far and "рывком" not in far
    assert rest["moved_ft"] == 20 and rest["left_ft"] == 0 and "dash" not in rest
    assert left["move_left_ft"] == 0 and not left["action"] and not left["bonus"]

    async def next_turn(ctx):
        sc = ctx.world.scene
        sc.state = {**sc.state, "turn": [x["id"] for x in sc.turn_order].index(gob)}
        idle = economy.view(ctx.world, hid)
        sc.round += 1
        sc.state = {**sc.state, "turn": [x["id"] for x in sc.turn_order].index(hid)}
        return idle, economy.view(ctx.world, hid)

    idle, back = play(settings, cid, [], next_turn)
    assert idle is None  # не его ход: ничего не считается
    assert back["action"] and back["bonus"] and back["move_left_ft"] == 30  # новый ход — чистый лист


def test_dash_action_doubles_steps(client, admin, settings):
    import_base(settings)
    c, _, hero = party(client, admin)
    cid, hid = c["id"], hero["id"]

    async def fn(ctx):
        await _ok(ctx, "create_location", {"name": "Поле", "make_current": True})
        spawn = {"creature_template_id": "creature.goblin", "name": "Гоблин", "cell": [10, 0]}
        gob = (await _ok(ctx, "spawn_entity", spawn))["spawned"][0]["id"]
        await _ok(ctx, "set_scene_mode", {"mode": "combat", "participants": [hid, gob]})
        sc = ctx.world.scene
        sc.state = {**sc.state, "turn": [x["id"] for x in sc.turn_order].index(hid)}
        dash = await call(ctx, "take_action", {"character_id": hid, "action": "dash"})
        run = await hero_step(ctx, hid, (-12, 0))  # 60 футов: рывок уже взят, вопросов нет
        return dash, run

    dash, run = play(settings, cid, [10, 10], fn)
    assert dash["ok"] and "шагов ещё 60 фт" in dash["result"]["left"]
    assert "confirm_needed" not in run and run["moved_ft"] == 60 and run["left_ft"] == 0
