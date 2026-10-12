# ruff: noqa: F811
"""Переход между участками (спецификация 2026-10-12, §5, §7, §8): сначала подготовка, потом проверка и шаг."""

from app.core import positions as grid
from app.core import steps
from app.core.layout import transit
from app.core.world_generation import storage
from app.db.models import Character, Entity, Event
from tests.game import run
from tests.test_layout_passages import _built
from tests.test_map import _ok, _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry, _prepare  # noqa: F401 — фикстура
from tests.test_ws import connect, next_of


def _go(client, head, cid, ref):
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "map.traverse", "payload": {"passage_ref": ref, "request_id": "r1"}})
        return next_of(ws, "map.traverse.result")["payload"]


def _place(settings, hid):
    return run(settings, lambda s: s.get(Character, hid)).location_id


def test_traverse_from_outside_prepares_then_moves(client, admin, settings):
    cid, heads, hid, village, _t, ids = _built(client, admin, settings)
    out = _go(client, heads[0], cid, "in_road_w")
    assert out["ok"] and out["moved"] and out["area_id"] == ids["road"]
    assert _place(settings, hid) == ids["road"] and out["cell"] in ([0, 3], [0, 4])
    geometry = run(settings, lambda s: storage.find(s, cid, ids["road"], "location_geometry"))
    assert geometry.status == "ready"
    assert len(rows(settings, Event, Event.tool == "traverse_passage")) == 1
    links = run(settings, lambda s: s.get(Entity, village)).state.get("links") or []
    assert ids["road"] not in {x["to"] for x in links}


def test_open_field_keeps_the_lane_both_ways(client, admin, settings):
    cid, heads, hid, _v, _t, ids = _built(client, admin, settings)
    _go(client, heads[0], cid, "in_road_w")
    east = _go(client, heads[0], cid, "p_brook")
    assert east["moved"] and east["cell"][0] == 0 and east["cell"][1] == east["from_cell"][1]
    west = _go(client, heads[0], cid, "p_brook")
    assert west["moved"] and west["cell"][0] == 11 and west["cell"][1] == west["from_cell"][1]
    assert _place(settings, hid) == ids["road"]


def test_closed_door_refuses(client, admin, settings):
    cid, heads, _hid, _v, _t, _ids = _built(client, admin, settings)
    _go(client, heads[0], cid, "in_road_w")
    out = _go(client, heads[0], cid, "p_narthex")
    assert not out["ok"] and "закрыт" in out["error"]


def test_hidden_passage_reads_as_missing(client, admin, settings):
    cid, heads, hid, _v, _t, ids = _built(client, admin, settings, "sacristy")

    async def go(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["sacristy"]})

    _play(settings, cid, go)
    secret, missing = _go(client, heads[0], cid, "p_vault"), _go(client, heads[0], cid, "p_nowhere")
    assert not secret["ok"] and secret["error"] == missing["error"] == "отсюда нет такого прохода"


def test_door_closed_during_preparation_keeps_area_but_not_hero(client, admin, settings):
    cid, heads, hid, _v, _t, ids = _built(client, admin, settings)
    _go(client, heads[0], cid, "in_road_w")

    async def begin(ctx):
        await _ok(ctx, "edit_sketch", {"action": "open", "target": "Двери храма", "location_id": ids["road"]})
        req = await transit.begin(ctx, [hid], "p_narthex", [])
        return req.to_json()

    req = _play(settings, cid, begin)
    assert req["refs"]

    async def close(ctx):
        await _ok(ctx, "edit_sketch", {"action": "close", "target": "Двери храма", "location_id": ids["road"]})

    _play(settings, cid, close)
    for ref in req["refs"]:
        _prepare(settings, cid, ref)

    async def finish(ctx):
        return await transit.finish(ctx, transit.Request.from_json(req))

    out = _play(settings, cid, finish)
    assert not out["moved"] and "закрыт" in out["reason"]
    assert _place(settings, hid) == ids["road"]
    geometry = run(settings, lambda s: storage.find(s, cid, ids["narthex"], "location_geometry"))
    assert geometry.status == "ready"


def test_walking_to_the_door_happens_before_preparation(client, admin, settings):
    cid, heads, hid, _v, _t, ids = _built(client, admin, settings)
    _go(client, heads[0], cid, "in_road_w")

    async def go(ctx):
        await _ok(ctx, "edit_sketch", {"action": "open", "target": "Двери храма", "location_id": ids["road"]})
        await transit.begin(ctx, [hid], "p_narthex", [])
        w = ctx.world
        return grid.to_master(w, ids["road"], steps.cell_of(w, hid)), w.actor_place(hid)

    cell, place = _play(settings, cid, go)
    assert cell == (6, 0) and place == ids["road"]  # у дверей, но ещё не внутри
