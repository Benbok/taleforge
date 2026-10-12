# ruff: noqa: F811
"""Соседство участков и зацепки каркаса (спецификация 2026-10-12, §3.1, §4)."""

from sqlalchemy import select

from app.core import plot_anchors
from app.core.layout import store
from app.core.topology import location_exits
from app.db.models import Entity, PlotAnchorBinding
from tests.game import run
from tests.test_layout_passages import _built
from tests.test_layout_preparation import _areas, _setup
from tests.test_map import _map, _ok, _play
from tests.test_world_generation import _fast_retry, _prepare  # noqa: F401 — фикстура


def _entities(settings):
    async def go(s):
        return {e.id: e for e in (await s.scalars(select(Entity))).all()}

    return run(settings, go)


def test_area_neighbours_follow_passages_not_nesting(client, admin, settings):
    cid, _h, _hid, village, temple, ids = _built(client, admin, settings)
    ents = _entities(settings)
    road = {x.target_id: x.label for x in location_exits(ents[ids["road"]], None, ents)}
    assert road == {ids["brook"]: "Луг", ids["narthex"]: "Двери храма", village: "Дорога в деревню"}
    assert ids["vault"] not in {x.target_id for x in location_exits(ents[ids["sacristy"]], None, ents)}
    assert not {x.target_id for x in location_exits(ents[temple], None, ents)} & set(ids.values())
    assert ids["road"] in {x.target_id for x in location_exits(ents[village], None, ents)}


def test_player_map_hides_secret_passage_and_area(client, admin, settings):
    cid, heads, hid, _v, _t, ids = _built(client, admin, settings, "sacristy")

    async def go(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["sacristy"]})

    _play(settings, cid, go)
    m = _map(client, heads[0], cid)
    assert ids["vault"] not in str(m) and "p_vault" not in str(m) and "Тайная дверь" not in str(m)


def test_root_anchor_follows_its_area(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)

    async def bind(ctx):
        village = (await _ok(ctx, "create_location", {"name": "Деревня", "make_current": True}))["location_id"]
        temple = (await _ok(ctx, "create_location", {"name": "Старый храм"}))["location_id"]
        for anchor in ("relic", "note"):
            ctx.session.add(PlotAnchorBinding(campaign_id=cid, anchor_id=anchor, plot_ref="r1",
                                              target_location_id=temple, state="reserved",
                                              source_snapshot={"carrier": {"name": anchor}}))  # fmt: skip
        return village, temple

    village, temple = _play(settings, cid, bind)
    from tests.layout_pilot import pilot_intent

    async def plan(ctx):
        intent = pilot_intent(village).model_dump(mode="json")
        return (await _ok(ctx, "prepare_complex", {"location_id": temple, "intent": intent}))["operation_ref"]

    _prepare(settings, cid, _play(settings, cid, plan))
    areas = {k: v.id for k, v in _areas(settings, temple).items()}
    root = _entities(settings)[temple]
    assert store.blueprint_of(root).anchors == {"relic": "chapel", "note": "road"}

    async def check(s):
        here = {a: [b.anchor_id for b in await plot_anchors.reserved_for(s, cid, x)] for a, x in areas.items()}
        return here, [b.anchor_id for b in await plot_anchors.reserved_for(s, cid, temple)]

    here, at_root = run(settings, check)
    assert here["chapel"] == ["relic"] and here["road"] == ["note"] and here["nave"] == [] and at_root == []
