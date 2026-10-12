# ruff: noqa: F811
"""Соседство участков и зацепки каркаса (спецификация 2026-10-12, §3.1, §4)."""

from sqlalchemy import select

from app.core import plot_anchors
from app.core.layout import store
from app.core.topology import location_exits
from app.db.models import Entity, PlotAnchorBinding
from tests.game import run
from tests.test_layout_passages import _built, _enter
from tests.test_layout_preparation import _activate, _areas, _complex, _setup
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


def test_player_map_exits_follow_passages(client, admin, settings):
    cid, heads, hid, village, temple, ids = _built(client, admin, settings, "road", "sacristy")

    exits_road = _exits_at(settings, client, heads, cid, hid, ids["road"])
    assert ids["brook"] not in exits_road and ids["narthex"] not in exits_road
    packet = _map(client, heads[0], cid)
    assert {x["via"] for x in packet["exits"] if x["id"] is None} == {"Луг", "Двери храма"}
    assert exits_road[village] == "Дорога в деревню" and temple not in exits_road
    exits_sacristy = _exits_at(settings, client, heads, cid, hid, ids["sacristy"])
    assert ids["vault"] not in exits_sacristy and temple not in exits_sacristy


def _exits_at(settings, client, heads, cid, hid, area):
    async def go(ctx):
        await _enter(ctx, hid, area)

    _play(settings, cid, go)
    return {x["id"]: x["via"] for x in _map(client, heads[0], cid)["exits"]}


def test_player_map_accepts_non_rect_area(client, admin, settings):
    cid, heads, hid = _setup(client, admin, settings)

    def circle(intent):
        next(p for p in intent["parts"] if p["part_ref"] == "sacristy")["shape"] = "circle"

    _village, temple, ref = _complex(settings, cid, circle)
    _prepare(settings, cid, ref)
    sacristy = _areas(settings, temple)["sacristy"].id
    _prepare(settings, cid, _activate(settings, cid, sacristy))

    async def go(ctx):
        await _enter(ctx, hid, sacristy)

    _play(settings, cid, go)
    sk = _map(client, heads[0], cid)["sketch"]
    assert sk["mask"] and len(sk["mask"]) == sk["rows"]


def test_revealed_passage_becomes_neighbour(client, admin, settings):
    cid, _h, hid, _v, _t, ids = _built(client, admin, settings, "sacristy", "vault")
    ents = _entities(settings)
    assert ids["vault"] not in {x.target_id for x in location_exits(ents[ids["sacristy"]], None, ents)}

    async def go(ctx):
        await _enter(ctx, hid, ids["sacristy"])
        await _ok(ctx, "edit_sketch", {"action": "reveal", "target": "Тайная дверь", "location_id": ids["sacristy"]})

    _play(settings, cid, go)
    ents = _entities(settings)
    assert ids["vault"] in {x.target_id for x in location_exits(ents[ids["sacristy"]], None, ents)}
    assert ids["sacristy"] in {x.target_id for x in location_exits(ents[ids["vault"]], None, ents)}


def test_map_parses_each_blueprint_once(client, admin, settings, monkeypatch):
    from app.core.layout.contracts import Blueprint

    cid, heads, hid, _v, _t, ids = _built(client, admin, settings, "road", "sacristy")
    for area in (ids["road"], ids["sacristy"]):

        async def enter(ctx, area=area):
            await _enter(ctx, hid, area)

        _play(settings, cid, enter)
    parsed = []
    original = Blueprint.from_json

    def spy(data):
        parsed.append(data)
        return original(data)

    monkeypatch.setattr(Blueprint, "from_json", spy)
    _map(client, heads[0], cid)
    assert len(parsed) == 1


def test_another_complex_approach_is_visible_and_traversable_from_area():
    from dataclasses import replace
    from types import SimpleNamespace

    from app.core.layout import transit
    from app.core.layout.contracts import End
    from tests.layout_pilot import two_rooms

    first = two_rooms()
    second = two_rooms()
    entrance = replace(second.passage("in_hall_w"), ends=(End("hall", "w", 1), End(place_id="cell1")))
    second = replace(second, passages=(second.passage("p_cell"), entrance))
    roots = [
        Entity(
            id="root1",
            kind="location",
            state={"blueprint": first.to_json(), "areas": {"hall": "hall1", "cell": "cell1"}},
        ),
        Entity(
            id="root2",
            kind="location",
            state={"blueprint": second.to_json(), "areas": {"hall": "hall2", "cell": "cell2"}},
        ),
    ]
    places = [
        Entity(
            id=ref + str(i),
            kind="location",
            location_id="root" + str(i),
            state={"complex": {"root_id": "root" + str(i), "area_ref": ref}},
        )
        for i in (1, 2)
        for ref in ("hall", "cell")
    ]
    ents = {e.id: e for e in [*roots, *places]}
    assert "hall2" in {x.target_id for x in location_exits(ents["cell1"], None, ents)}
    root, _bp, _p, end, other = transit.find_passage(SimpleNamespace(entities=ents), "cell1", "in_hall_w")
    assert root.id == "root2" and end.external and other.area_ref == "hall"
