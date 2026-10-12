# ruff: noqa: F811
"""Проход комплекса общий для двух участков (спецификация 2026-10-12, §4): одно состояние, правка только корня."""

from types import SimpleNamespace

from app.agents import surveyor
from app.core import sketch
from app.db.models import Entity
from app.tools.registry import execute
from tests.game import run
from tests.test_layout_preparation import _activate, _areas, _complex, _setup
from tests.test_map import _ok, _play
from tests.test_world_generation import _fast_retry, _prepare, _with_maker  # noqa: F401 — фикстура


def _built(client, admin, settings, *names):
    """Комплекс подготовлен, у перечисленных участков готова геометрия."""
    cid, heads, hid = _setup(client, admin, settings)
    village, temple, ref = _complex(settings, cid)
    _prepare(settings, cid, ref)
    areas = _areas(settings, temple)
    for name in names:
        _prepare(settings, cid, _activate(settings, cid, areas[name].id))
    return cid, heads, hid, village, temple, {k: v.id for k, v in areas.items()}


def _exit(w, place, ref):
    sk = sketch.of_place(w.entities[place], w.catalog, w.entities)
    return next(x for x in sk["exits"] if x.get("passage_ref") == ref)


async def _enter(ctx, hid, area_id):
    """Герой стоит в участке: инструменты правки эскиза принимают только места, где стоят герои."""
    await _ok(ctx, "move", {"character_ids": [hid], "location_id": area_id})


def test_door_state_is_shared_by_both_sides(client, admin, settings):
    cid, _h, hid, _v, temple, ids = _built(client, admin, settings, "road", "narthex")

    async def go(ctx):
        w = ctx.world
        assert _exit(w, ids["road"], "p_narthex")["state"] == _exit(w, ids["narthex"], "p_narthex")["state"] == "closed"
        await _enter(ctx, hid, ids["road"])
        await _ok(ctx, "edit_sketch", {"action": "open", "target": "Двери храма", "location_id": ids["road"]})
        opened = (_exit(w, ids["road"], "p_narthex")["state"], _exit(w, ids["narthex"], "p_narthex")["state"])
        await _enter(ctx, hid, ids["narthex"])
        removed = await execute(ctx, "edit_sketch", {"action": "remove", "target": "Двери храма",
                                                     "location_id": ids["narthex"]})  # fmt: skip
        stored = w.entities[ids["road"]].state["sketch"]
        table = sketch.describe(sketch.of_place(w.entities[ids["road"]], w.catalog, w.entities))
        return opened, removed, stored, table

    opened, removed, stored, table = _play(settings, cid, go)
    assert opened == ("open", "open")
    assert not removed["ok"] and "общий для двух участков" in removed["error"]
    assert next(x for x in stored["exits"] if x["passage_ref"] == "p_narthex")["state"] == "closed"  # эскиз не правят
    assert "проход p_narthex" in table
    root = run(settings, lambda s: s.get(Entity, temple))
    assert root.state["passages"]["p_narthex"]["state"] == "open"


def test_secret_door_revealed_once_for_both_sides(client, admin, settings):
    cid, _h, hid, _v, _t, ids = _built(client, admin, settings, "sacristy", "vault")

    async def go(ctx):
        w = ctx.world
        before = _exit(w, ids["vault"], "p_vault")["hidden"]
        await _enter(ctx, hid, ids["sacristy"])
        await _ok(ctx, "edit_sketch", {"action": "reveal", "target": "Тайная дверь", "location_id": ids["sacristy"]})
        return before, _exit(w, ids["vault"], "p_vault")["hidden"]

    assert _play(settings, cid, go) == (True, False)


def test_surveyor_and_redraw_do_not_replace_blueprint_sketch(client, admin, settings):
    cid, _h, hid, _v, _t, ids = _built(client, admin, settings, "road")

    async def describe(ctx):
        await _enter(ctx, hid, ids["road"])
        layout = "Поле у дороги, сорок футов в каждую сторону, на севере стена храма, двери закрыты."
        await _ok(ctx, "describe_place", {"layout": layout, "location_id": ids["road"]})
        redraw = await execute(ctx, "sketch_place", {"shape": "open", "cols": 4, "rows": 4, "party": [0, 0],
                                                     "location_id": ids["road"]})  # fmt: skip
        return redraw

    redraw = _play(settings, cid, describe)
    assert not redraw["ok"] and "участок комплекса" in redraw["error"]
    drawn = _with_maker(settings, lambda maker: surveyor.draw(SimpleNamespace(maker=maker), cid, ids["road"]))
    assert drawn is None
    road = run(settings, lambda s: s.get(Entity, ids["road"]))
    assert road.state["sketch"]["blueprint"]["area_ref"] == "road"
