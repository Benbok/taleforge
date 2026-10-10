# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Схема места и карта открытых мест: карта собирается из реестра, мастер пополняет её инструментами."""

from app.db.models import Campaign, Entity
from app.tools.registry import execute
from app.tools.runtime import flush_outbox, open_context
from tests.game import FIGHTER, QueueDice, import_base, ok, party, run
from tests.test_ws import connect, next_of


def _play(settings, cid, fn):
    async def go(s):
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice([]), turn_id="t_map", seat_id=None)
        out = await fn(ctx)
        await flush_outbox(s, ctx)
        await s.commit()
        return out

    return run(settings, go)


async def _ok(ctx, name, args):
    r = await execute(ctx, name, args)
    assert r["ok"], r
    return r["result"]


def _map(client, head, cid):
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "map.get", "payload": {}})
        return next_of(ws, "map.state")["payload"]


def test_map_shows_surroundings_exits_and_hides_secrets(client, admin, settings):
    import_base(settings)
    c, (p1, p2), hero = party(client, admin, players=2)
    cid, hid = c["id"], hero["id"]

    async def build(ctx):
        square = (await _ok(ctx, "create_location", {"name": "Рыночная площадь", "make_current": True}))["location_id"]
        shop = await _ok(ctx, "create_location", {"name": "Лавка косторез", "parent_id": square})
        docks = await _ok(
            ctx, "create_location", {"name": "Трюмные доки", "link_to": [square], "via": "переулок", "bearing": "e"}
        )
        stash = await _ok(ctx, "create_location", {"name": "Тайник", "parent_id": square, "secret": True})
        far = await _ok(ctx, "create_location", {"name": "Склад на окраине"})
        gob = await _ok(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Гоблин", "zone": "far", "bearing": "n"},
        )
        mark = await _ok(ctx, "add_landmark", {"name": "Фонтан", "zone": "near", "bearing": "s"})
        return {
            "square": square,
            "shop": shop["location_id"],
            "docks": docks["location_id"],
            "stash": stash["location_id"],
            "far": far["location_id"],
            "gob": gob["spawned"][0]["id"],
            "mark": mark["landmark_id"],
        }

    ids = _play(settings, cid, build)

    # Ключ вида живёт в состоянии Entity; карта только передаёт его клиенту.
    # Новые шаблоны предметов смогут выбирать значки, не меняя рендерер карт.
    async def appearance(session):
        mark = await session.get(Entity, ids["mark"])
        mark.state = {**(mark.state or {}), "visual_key": "landmark:torch"}
        await session.commit()

    run(settings, appearance)
    m = _map(client, p1, cid)
    assert m["here"]["id"] == ids["square"]
    around = {x["id"]: x for x in m["around"]}
    assert around[ids["gob"]]["zone"] == "far" and around[ids["gob"]]["bearing"] == "n"
    assert around[ids["gob"]]["type"] == "creature" and around[ids["gob"]]["condition"] == "невредим"
    assert around[ids["mark"]]["type"] == "landmark" and around[ids["mark"]]["bearing"] == "s"
    assert around[ids["mark"]]["visual_key"] == "landmark:torch"
    scene_tokens = {t["id"]: t for t in m["scene_view"]}
    assert scene_tokens[ids["gob"]]["type"] == "creature"
    assert scene_tokens[ids["mark"]]["type"] == "landmark"
    assert scene_tokens[ids["mark"]]["visual_key"] == "landmark:torch"
    assert {t["id"] for t in m["scene_view"]} == {
        *(t["id"] for t in m["around"]),
        *(h["id"] for h in m["party"]),
    }
    exits = {x["id"]: x for x in m["exits"]}
    assert exits[ids["shop"]]["via"] == "внутри" and not exits[ids["shop"]]["visited"]
    assert exits[ids["docks"]]["via"] == "переулок" and exits[ids["docks"]]["bearing"] == "e"
    shown = {p["id"]: p for p in m["places"]}
    assert ids["stash"] not in shown and ids["far"] not in shown  # тайник не найден, про склад не слышали
    assert shown[ids["square"]]["status"] == "here" and shown[ids["shop"]]["parent_id"] == ids["square"]
    assert {(x["a"], x["b"]) for x in m["links"]} == {tuple(sorted((ids["square"], ids["docks"])))}

    # герой ушёл в доки: площадь посещена, второй путь не заводится
    async def go_docks(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["docks"]})

    _play(settings, cid, go_docks)
    m = _map(client, p1, cid)
    shown = {p["id"]: p["status"] for p in m["places"]}
    assert m["here"]["id"] == ids["docks"] and shown[ids["square"]] == "visited" and shown[ids["docks"]] == "here"
    assert len(m["links"]) == 1 and ids["gob"] not in {x["id"] for x in m["around"]}
    assert [x["via"] for x in m["exits"]] == ["переулок"]

    # тайник нашли: он на карте; через make_current путь из доков отмечается сам
    async def find(ctx):
        await _ok(ctx, "link_locations", {"from_id": ids["docks"], "to_id": ids["far"], "via": "люк"})
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["stash"]})

    _play(settings, cid, find)
    m = _map(client, p1, cid)
    shown = {p["id"]: p["status"] for p in m["places"]}
    assert shown[ids["stash"]] == "here" and shown[ids["far"]] == "known"

    async def states(s):
        return (await s.get(Entity, ids["docks"])).state

    st = run(settings, states)
    assert st["visited_by"] == [hid] and {x["to"] for x in st["links"]} == {ids["square"], ids["far"], ids["stash"]}

    # второй игрок без героя видит карту отряда
    m2 = _map(client, p2, cid)
    assert m2["here"]["id"] == ids["stash"] and ids["square"] in {p["id"] for p in m2["places"]}


def test_positions_distance_cover_and_areas(client, admin, settings):
    import_base(settings)
    c, (p1,), hero = party(client, admin)
    cid, hid = c["id"], hero["id"]

    async def fight(ctx):
        sq = (await _ok(ctx, "create_location", {"name": "Площадь", "make_current": True}))["location_id"]
        spawn = {"creature_template_id": "creature.goblin", "name": "Гоблин", "zone": "near", "bearing": "n"}
        gob = (await _ok(ctx, "spawn_entity", spawn))["spawned"][0]["id"]
        w = ctx.world
        assert w.distance_ft(w.actor(hid), w.actor(gob)) == 30  # герой в строю: до гоблина его зона
        # герой вышел на восток близко: до гоблина на севере — диагональ
        r = await _ok(ctx, "reposition", {"actor_id": hid, "zone": "near", "bearing": "e"})
        assert r["moved_ft"] == 30
        assert ctx.world.distance_ft(ctx.world.actor(hid), ctx.world.actor(gob)) == 40
        # гоблин залез на возвышение и спрятался за парапет: расстояние растёт, КД +2
        await _ok(ctx, "update_entity", {"entity_id": gob, "elevation": "high", "cover": "half"})
        assert ctx.world.distance_ft(ctx.world.actor(hid), ctx.world.actor(gob)) == 45
        await _ok(ctx, "set_scene_mode", {"mode": "combat"})
        far = await execute(ctx, "reposition", {"actor_id": hid, "zone": "far", "bearing": "w"})
        assert not far["ok"] and "рывком" in far["error"]
        await _ok(ctx, "update_entity", {"entity_id": gob, "cover": "total"})
        shot = await execute(ctx, "resolve_attack", {"attacker_id": hid, "target_id": gob, "attack": "item.longsword"})
        assert not shot["ok"] and "полным укрытием" in shot["error"]
        await _ok(ctx, "update_entity", {"entity_id": gob, "cover": "half", "zone": "melee", "elevation": "ground"})
        await _ok(ctx, "reposition", {"actor_id": hid, "zone": "center"})
        hit = await _ok(ctx, "resolve_attack", {"attacker_id": hid, "target_id": gob, "attack": "item.longsword"})
        assert hit["target_ac"] == 17 and "укрытие" in hit["cover"]
        # облако яда вокруг отряда: герой внутри сразу, гоблин — когда войдёт
        bad = await execute(ctx, "place_area", {"name": "Обрыв", "hazard_template_id": "hazard.falling"})
        assert not bad["ok"] and "параметры" in bad["error"]
        area = await _ok(
            ctx,
            "place_area",
            {"name": "Ядовитое облако", "zone": "melee", "radius_ft": 10, "effect_template_id": "condition.poisoned",
             "duration_rounds": 3},
        )  # fmt: skip
        assert area["inside"] == ["Бран", "Гоблин"] and area["hits"][0]["effect"]
        return sq, gob, area["area_id"]

    sq, gob, area_id = _play(settings, cid, fight)

    m = _map(client, p1, cid)
    assert [a["id"] for a in m["areas"]] == [area_id] and m["areas"][0]["radius_ft"] == 10
    assert area_id not in {x["id"] for x in m["around"]}
    me = m["party"][0]
    assert me["mine"] and me["zone"] is None
    assert next(x for x in m["around"] if x["id"] == gob)["cover"] == "half"

    async def leave(ctx):
        docks = (await _ok(ctx, "create_location", {"name": "Доки"}))["location_id"]
        await _ok(ctx, "reposition", {"actor_id": hid, "zone": "near", "bearing": "s"})
        assert "positions" in ctx.world.scene.state
        await _ok(ctx, "set_scene_mode", {"mode": "free"})
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": docks})
        return "positions" in (ctx.world.scene.state or {})

    assert _play(settings, cid, leave) is False  # в новом месте герой снова в строю


def test_partial_move_clears_hero_positions_and_emits_map_changed(client, admin, settings):
    import_base(settings)
    c, (p1, p2), h1 = party(client, admin, players=2, master={"type": "owner"})
    cid, hid1 = c["id"], h1["id"]
    h2 = ok(client.post(f"/api/campaigns/{cid}/characters", json={**FIGHTER, "name": "Гимли"}, headers=p2), 201)
    ok(client.post(f"/api/campaigns/{cid}/characters/{h2['id']}/submit", headers=p2))
    hid2 = h2["id"]

    async def setup(ctx):
        sq = (await _ok(ctx, "create_location", {"name": "Площадь", "make_current": True}))["location_id"]
        docks = (await _ok(ctx, "create_location", {"name": "Доки"}))["location_id"]
        await _ok(ctx, "reposition", {"actor_id": hid1, "zone": "near", "bearing": "s"})
        await _ok(ctx, "reposition", {"actor_id": hid2, "zone": "melee", "bearing": "n"})
        assert hid1 in (ctx.world.scene.state or {}).get("positions", {})
        assert hid2 in (ctx.world.scene.state or {}).get("positions", {})
        # Перемещаем только первого героя в доки:
        await _ok(ctx, "move", {"character_ids": [hid1], "location_id": docks})
        assert "map.changed" in ctx.signals
        pos = (ctx.world.scene.state or {}).get("positions", {})
        assert hid1 not in pos
        assert hid2 in pos
        return sq, docks

    sq, docks = _play(settings, cid, setup)

    # Через сокет живого мастера: перемещение второго героя шлёт map.changed всем подключённым
    with connect(client, p1, cid) as (ws1, _), connect(client, admin, cid) as (ws_m, _):
        ws_m.send_json(
            {
                "type": "master.tool",
                "payload": {"tool": "move", "args": {"character_ids": [hid2], "location_id": docks}},
            }
        )
        ev = next_of(ws1, "map.changed")
        assert ev["type"] == "map.changed"
