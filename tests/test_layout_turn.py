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


def test_republish_failure_does_not_interrupt_completed_turn(game_client, admin_g, llm, settings, monkeypatch):
    from app.core.layout import transit
    from app.db.models import MasterTurn

    c, (p1,), hero = party(game_client, admin_g)
    cid = c["id"]
    ids = _temple(settings, cid)

    async def broken(*args, **kwargs):
        raise RuntimeError("сбой публикации")

    seen = []
    original = game_client.app.state.bus.publish

    async def spy(campaign_id, event, seats=None, *args, **kwargs):
        seen.append(event)
        return await original(campaign_id, event, seats, *args, **kwargs)

    monkeypatch.setattr(game_client.app.state.bus, "publish", spy)
    monkeypatch.setattr(transit, "republish", broken)
    llm.replies += [
        {"tool_calls": [("traverse_passage", {"passage_ref": "in_road_w"})]},
        DONE,
        {"text": "Пыльная дорога у храма."},
    ]
    act(game_client, p1, cid, "Иду по дороге к храму")
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    assert run(settings, lambda s: s.get(Character, hero["id"])).location_id == ids["road"]
    assert rows(settings, MasterTurn)[-1].status == "done"
    assert any(e["type"] == "message.state" and e["payload"]["state"] == "answered" for e in seen)


def test_recovery_completes_panel_transit_without_master_turn(game_client, admin_g, settings):
    c, _p, hero = party(game_client, admin_g)
    cid = c["id"]
    ids = _temple(settings, cid)

    async def queue(ctx):
        ctx.turn_id = None  # очередь панели не принадлежит ходу мастера
        return await _ok(ctx, "traverse_passage", {"passage_ref": "in_road_w"})

    assert _play(settings, cid, queue)["queued"]
    game_client.portal.call(game_client.app.state.master.recover)
    assert run(settings, lambda s: s.get(Character, hero["id"])).location_id == ids["road"]
    assert not run(settings, lambda s: s.get(Scene, cid)).state.get("transits")


def test_panel_transit_finishes_in_background(game_client, admin_g, settings):
    from tests.test_ws import connect, next_of

    c, _p, hero = party(game_client, admin_g, master={"type": "owner"})
    cid = c["id"]
    ids = _temple(settings, cid)
    with connect(game_client, admin_g, cid) as (ws, _):
        ws.send_json(
            {
                "type": "master.tool",
                "payload": {"tool": "traverse_passage", "args": {"passage_ref": "in_road_w"}, "request_id": "panel"},
            }
        )
        result = next_of(ws, "master.tool.result")["payload"]
        assert result["ok"] and result["result"]["queued"]
        for _ in range(40):
            event = ws.receive_json()
            if event["type"] == "map.changed":
                if run(settings, lambda s: s.get(Character, hero["id"])).location_id == ids["road"]:
                    break
        else:
            raise AssertionError("переход с панели не завершился")
    assert not run(settings, lambda s: s.get(Scene, cid)).state.get("transits")


def test_split_party_narration_follows_transiting_crew(game_client, admin_g, llm, settings, monkeypatch):
    from tests.game import FIGHTER, ok

    c, (p1, p2), hero = party(game_client, admin_g, players=2, start=False)
    cid = c["id"]
    second = ok(game_client.post(f"/api/campaigns/{cid}/characters", json=FIGHTER, headers=p2), 201)
    ok(game_client.post(f"/api/campaigns/{cid}/characters/{second['id']}/submit", headers=p2))
    ok(game_client.post(f"/api/campaigns/{cid}/session/start", headers=admin_g))
    ids = _temple(settings, cid)

    async def separate(ctx):
        far = (await _ok(ctx, "create_location", {"name": "Далёкая башня"}))["location_id"]
        await _ok(ctx, "move", {"character_ids": [second["id"]], "location_id": far})

    _play(settings, cid, separate)
    seen = []
    master = game_client.app.state.master
    original = master._system_prompt

    async def spy(s, c, cfg, ctx):
        seen.append(ctx.world.scene_places())
        return await original(s, c, cfg, ctx)

    monkeypatch.setattr(master, "_system_prompt", spy)
    llm.replies += [
        {"tool_calls": [("traverse_passage", {"passage_ref": "in_road_w", "character_ids": [hero["id"]]})]},
        DONE,
        {"text": "Герой вышел на дорогу."},
    ]
    from tests.test_ws import connect

    with connect(game_client, p1, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Иду к храму"}})
        for _ in range(40):
            event = ws.receive_json()
            if event["type"] == "message.new" and event["payload"]["kind"] == "narration":
                break
        else:
            raise AssertionError("нет повествования группе")
    game_client.portal.call(master.wait_idle, cid)
    assert seen[-1] == [ids["road"]]


def test_default_transit_uses_focused_group(client, admin, settings):
    from tests.game import FIGHTER, import_base, ok, quiet

    import_base(settings)
    c, (_p1, p2), hero = party(client, admin, players=2, start=False)
    cid = c["id"]
    second = ok(client.post(f"/api/campaigns/{cid}/characters", json=FIGHTER, headers=p2), 201)
    ok(client.post(f"/api/campaigns/{cid}/characters/{second['id']}/submit", headers=p2))
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


def test_preparing_resume_waits_outside_database_transaction(game_client, admin_g, llm, settings, monkeypatch):
    from contextlib import asynccontextmanager

    from app.db.models import MasterTurn

    c, (p1,), _hero = party(game_client, admin_g)
    cid = c["id"]
    _temple(settings, cid)
    llm.replies += [
        {"tool_calls": [("traverse_passage", {"passage_ref": "in_road_w"})]},
        DONE,
        {"text": "Герой на дороге."},
    ]
    act(game_client, p1, cid, "Иду к храму")
    turn = rows(settings, MasterTurn)[-1]

    async def rewind(s):
        t = await s.get(MasterTurn, turn.id)
        t.status = "running"
        t.generation_checkpoint = {**t.generation_checkpoint, "stage": "preparing", "attempts": 0}
        await s.commit()

    run(settings, rewind)
    master = game_client.app.state.master
    original_maker, original_settle = master.maker, master.preparer.settle
    active, transactions = [], []

    @asynccontextmanager
    async def maker():
        async with original_maker() as s:
            active.append(s)
            try:
                yield s
            finally:
                active.remove(s)

    async def settle(*args):
        transactions.append(any(s.in_transaction() for s in active))
        await original_settle(*args)

    monkeypatch.setattr(master, "maker", maker)
    monkeypatch.setattr(master.preparer, "settle", settle)
    llm.replies += [{"text": "Герой всё ещё на дороге."}]
    game_client.portal.call(master._narrate_turn, cid, turn.id)
    assert transactions and not any(transactions)


def test_transit_event_survives_publication_failure_in_checkpoint(game_client, admin_g, llm, settings, monkeypatch):
    from app.core.layout import transit
    from app.db.models import MasterTurn

    c, (p1,), _hero = party(game_client, admin_g)
    cid = c["id"]
    _temple(settings, cid)
    original = transit.complete_queued

    class BrokenBus:
        async def publish(self, *args, **kwargs):
            raise RuntimeError("сбой рассылки перехода")

    async def complete(*args, **kwargs):
        return await original(*args, **{**kwargs, "bus": BrokenBus()})

    monkeypatch.setattr(transit, "complete_queued", complete)
    llm.replies += [
        {"tool_calls": [("traverse_passage", {"passage_ref": "in_road_w"})]},
        DONE,
        {"text": "Герой на дороге."},
    ]
    act(game_client, p1, cid, "Иду к храму")
    turn = rows(settings, MasterTurn)[-1]
    moved = rows(settings, Event, Event.tool == "traverse_passage", Event.turn_id == turn.id)
    moved = [e for e in moved if e.payload.get("moved")]
    assert len(moved) == 1 and moved[0].id in turn.generation_checkpoint["event_ids"]
    assert turn.status == "done"


def test_republish_sends_after_database_session_closes(game_client, admin_g, settings):
    from contextlib import asynccontextmanager

    from app.core.layout import transit

    c, _p, hero = party(game_client, admin_g)
    active, transactions = [], []
    original = game_client.app.state.sessionmaker

    @asynccontextmanager
    async def maker():
        async with original() as s:
            active.append(s)
            try:
                yield s
            finally:
                active.remove(s)

    class Bus:
        async def publish(self, *args, **kwargs):
            transactions.append(any(s.in_transaction() for s in active))

    game_client.portal.call(transit.republish, maker, game_client.app.state.dice_factory, Bus(), c["id"], [hero["id"]])
    assert transactions and not any(transactions)


def test_queue_conflict_keeps_turn_preparing_for_recovery(game_client, admin_g, llm, settings, monkeypatch):
    import pytest

    from app.core.layout import transit
    from app.core.world_tx import WorldConflict
    from app.db.models import MasterTurn
    from tests.test_world_generation import _with_maker

    c, (p1,), _hero = party(game_client, admin_g)
    cid = c["id"]
    _temple(settings, cid)
    original = transit.finish

    async def conflict(*args, **kwargs):
        raise WorldConflict(cid, 0)

    monkeypatch.setattr(transit, "finish", conflict)
    # Сбой между загрузкой мира и фиксацией не должен разрешить описание.
    llm.replies += [{"tool_calls": [("traverse_passage", {"passage_ref": "in_road_w"})]}, DONE]
    from tests.test_ws import connect

    master = game_client.app.state.master
    # В этом тесте восстановление запускается явно после проверки checkpoint.
    monkeypatch.setattr(master, "signal_recovery", lambda: None)
    with connect(game_client, p1, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Иду к храму"}})
        # До ошибки мастер сообщает processing; затем дождёмся завершения фонового хода.
        from tests.test_ws import next_of

        next_of(ws, "master.status")
        game_client.portal.call(master.wait_idle, cid)
    turn = rows(settings, MasterTurn)[-1]
    assert turn.status == "running" and turn.generation_checkpoint["stage"] == "preparing"
    assert run(settings, lambda s: s.get(Scene, cid)).state.get("transits")

    async def complete(maker):
        return await transit.complete_queued(maker, master.preparer, master.dice_factory, cid, turn_id=turn.id)

    with pytest.raises(WorldConflict):
        _with_maker(settings, complete)
    monkeypatch.setattr(transit, "finish", original)
    llm.replies += [{"text": "Герой вышел на дорогу."}]
    game_client.portal.call(master.recover)
    assert rows(settings, MasterTurn)[-1].status == "done"
    assert not run(settings, lambda s: s.get(Scene, cid)).state.get("transits")
