# ruff: noqa: F811
"""Переход мастера в ходе (спецификация 2026-10-12, §8): описание — только после зафиксированного перехода."""

from app.core.layout import store
from app.core.world_generation import storage
from app.db.models import Character, Event, Scene
from tests.game import party, run
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


def test_turn_moves_through_passage_before_narration(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    cid, hid = c["id"], hero["id"]
    ids = _temple(settings, cid)
    llm.replies += [{"tool_calls": [("traverse_passage", {"passage_ref": "in_road_w"})]}, DONE,
                    {"text": "Пыльная дорога у храма."}]  # fmt: skip
    told = act(game_client, p1, cid, "Иду по дороге к храму")
    assert told["kind"] == "narration"
    assert run(settings, lambda s: s.get(Character, hid)).location_id == ids["road"]
    assert not (run(settings, lambda s: s.get(Scene, cid)).state or {}).get("transits")
    moved = [e for e in rows(settings, Event, Event.tool == "traverse_passage") if e.payload.get("moved")]
    assert len(moved) == 1
    assert "Дорога у храма" in str(llm.requests[-1]["messages"])  # описание видит уже новый участок


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


def test_turn_publishes_the_new_area_after_narration(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    cid = c["id"]
    ids = _temple(settings, cid)
    bus, seen = game_client.app.state.bus, []
    original = bus.publish

    async def spy(campaign_id, event, seats=None, *a, **kw):
        seen.append((event["type"], str(event["payload"])))
        return await original(campaign_id, event, seats, *a, **kw)

    bus.publish = spy
    llm.replies += [{"tool_calls": [("traverse_passage", {"passage_ref": "in_road_w"})]}, DONE,
                    {"text": "Пыльная дорога у храма."}]  # fmt: skip
    act(game_client, p1, cid, "Иду по дороге к храму")
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    kinds = [k for k, _ in seen]
    last_narration = max(i for i, (k, p) in enumerate(seen) if k == "message.new" and "narration" in p)
    after = [(k, p) for k, p in seen[last_narration:] if k == "scene.updated"]
    assert after and ids["road"] in after[-1][1]
    assert "map.changed" in kinds[last_narration:]


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
