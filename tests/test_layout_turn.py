# ruff: noqa: F811
"""Переход мастера в ходе (спецификация 2026-10-12, §8): описание — только после зафиксированного перехода."""

from app.core.layout import store
from app.core.world_generation import storage
from app.db.models import Character, Event, Scene
from tests.game import add_hero, party, run
from tests.layout_pilot import pilot_intent
from tests.test_layout_preparation import _activate, _areas
from tests.test_map import _ok, _play
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры хода
from tests.test_world_generation import _fast_retry, _prepare  # noqa: F401 — фикстура


def _temple(settings, cid):
    async def go(ctx):
        village = (await _ok(ctx, "create_location", {"name": "Деревня", "make_current": True}))["location_id"]
        temple = (await _ok(ctx, "create_location", {"name": "Старый храм"}))["location_id"]
        intent = pilot_intent(village).model_dump(mode="json")
        return temple, (await _ok(ctx, "prepare_complex", {"location_id": temple, "intent": intent}))["operation_ref"]

    temple, ref = _play(settings, cid, go)
    _prepare(settings, cid, ref)
    return {k: v.id for k, v in _areas(settings, temple).items()}


def test_ready_destination_moves_inside_the_tool(client, admin, settings):
    from tests.game import import_base, quiet

    import_base(settings)
    c, _heads, hero = party(client, admin)
    quiet(client)
    cid = c["id"]
    ids = _temple(settings, cid)
    _prepare(settings, cid, _activate(settings, cid, ids["road"]))

    async def go(ctx):
        out = await _ok(ctx, "traverse_passage", {"passage_ref": "in_road_w"})
        return out, sorted(ctx.operation_refs)

    out, refs = _play(settings, cid, go)
    assert out["moved"] and out["area_id"] == ids["road"] and refs == []


def test_move_into_area_requests_its_geometry(client, admin, settings):
    from tests.game import import_base, quiet

    import_base(settings)
    c, _heads, hero = party(client, admin)
    quiet(client)
    cid, hid = c["id"], hero["id"]
    ids = _temple(settings, cid)

    async def go(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["brook"]})
        geo = await storage.find(ctx.session, cid, ids["brook"], "location_geometry")
        return geo.id, set(ctx.operation_refs), store.complex_of(ctx.world.entities[ids["brook"]])

    geo, refs, cx = _play(settings, cid, go)
    assert geo in refs and cx["area_ref"] == "brook"


def test_queued_transit_completes_once(game_client, admin_g, llm, settings):
    from app.core.layout import transit
    from app.db.models import Message
    from tests.test_world_generation import _with_maker

    c, _p, hero = party(game_client, admin_g)
    cid, hid = c["id"], hero["id"]
    ids = _temple(settings, cid)

    async def go(ctx):
        return await _ok(ctx, "traverse_passage", {"passage_ref": "in_road_w"})

    assert _play(settings, cid, go)["queued"]
    orch = game_client.app.state.master.preparer

    async def twice(maker):
        factory = game_client.app.state.dice_factory
        first = await transit.complete_queued(maker, orch, factory, cid)
        again = await transit.complete_queued(maker, orch, factory, cid)
        return first, again

    first, again = _with_maker(settings, twice)
    assert len(first) == 1 and again == []
    assert run(settings, lambda s: s.get(Character, hid)).location_id == ids["road"]
    moved = [e for e in rows(settings, Event, Event.tool == "traverse_passage") if e.payload.get("moved")]
    assert len(moved) == 1
    assert not [m for m in rows(settings, Message) if "Переход не состоялся" in (m.content or "")]


def test_default_transit_uses_focused_group(client, admin, settings):
    from tests.game import import_base, ok, quiet

    import_base(settings)
    c, (_p1, p2), hero = party(client, admin, players=2, start=False)
    cid = c["id"]
    second = add_hero(client, cid, p2)
    ok(client.post(f"/api/campaigns/{cid}/session/start", headers=admin))
    quiet(client)
    ids = _temple(settings, cid)
    _prepare(settings, cid, _activate(settings, cid, ids["road"]))

    async def go(ctx):
        await _ok(ctx, "move", {"character_ids": [second["id"]], "location_id": ids["road"]})
        ctx.world.focus = ids["road"]
        ctx.world.crew = {second["id"]}
        return await _ok(ctx, "traverse_passage", {"passage_ref": "p_brook"})

    assert _play(settings, cid, go)["queued"]
    queue = run(settings, lambda s: s.get(Scene, cid)).state["transits"]
    assert queue[0]["hero_ids"] == [second["id"]]
    assert run(settings, lambda s: s.get(Character, hero["id"])).location_id != ids["brook"]
