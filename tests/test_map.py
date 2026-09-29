# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Схема места и карта открытых мест: карта собирается из реестра, мастер пополняет её инструментами."""

from app.db.models import Campaign, Entity
from app.tools.registry import execute
from app.tools.runtime import flush_outbox, open_context
from tests.game import QueueDice, import_base, party, run
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
    m = _map(client, p1, cid)
    assert m["here"]["id"] == ids["square"]
    around = {x["id"]: x for x in m["around"]}
    assert around[ids["gob"]]["zone"] == "far" and around[ids["gob"]]["bearing"] == "n"
    assert around[ids["gob"]]["type"] == "creature" and around[ids["gob"]]["condition"] == "невредим"
    assert around[ids["mark"]]["type"] == "landmark" and around[ids["mark"]]["bearing"] == "s"
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
