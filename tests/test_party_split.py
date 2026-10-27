# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Разделение отряда (design/party-split.md): мастер видит существ там, где стоит каждый герой, а игрок видит
окружение своего места."""

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import ScriptedLLM
from app.core import audio
from app.db.models import Campaign
from app.main import create_app
from app.tools.registry import execute
from app.tools.runtime import open_context, scene_views
from tests.conftest import login
from tests.game import QueueDice, add_hero, import_base, ok, party, quiet, run
from tests.test_map import _ok, _play
from tests.test_ws import connect, next_of


def _split_party(client, admin, settings, **kw):
    """Два героя на площади, второй уходит в доки; в доках гоблин, на площади фонтан."""
    import_base(settings)
    c, (p1, p2), h1 = party(client, admin, players=2, start=False, **kw)
    cid = c["id"]
    h2 = add_hero(client, cid, p2, "Гимли")
    ok(client.post(f"/api/campaigns/{cid}/session/start", headers=admin))
    quiet(client)

    async def build(ctx):
        square = (await _ok(ctx, "create_location", {"name": "Площадь", "make_current": True}))["location_id"]
        docks = (await _ok(ctx, "create_location", {"name": "Доки", "link_to": [square]}))["location_id"]
        fountain = (await _ok(ctx, "add_landmark", {"name": "Фонтан"}))["landmark_id"]
        await _ok(ctx, "move", {"character_ids": [h2["id"]], "location_id": docks})
        assert ctx.world.split
        lost = await execute(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"})
        assert not lost["ok"] and "отряд разделён" in lost["error"]
        gob = await _ok(
            ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин", "location_id": docks}
        )
        return {"square": square, "docks": docks, "fountain": fountain, "gob": gob["spawned"][0]["id"]}

    ids = _play(settings, cid, build)
    quiet(client)
    return cid, (p1, p2), (h1, h2), ids


def test_snapshot_update_and_map_agree_for_viewer(client, admin, settings):
    cid, (p1, p2), (_, _), ids = _split_party(client, admin, settings)
    expected = [(p1, ids["square"], {ids["fountain"]}), (p2, ids["docks"], {ids["gob"]})]
    for headers, location, entities in expected:
        with connect(client, headers, cid) as (ws, snapshot):
            scene = snapshot["payload"]["scene"]
            assert scene["location"]["id"] == location
            assert {e["id"] for e in scene["entities"]} == entities
            ws.send_json({"type": "map.get", "payload": {}})
            board = next_of(ws, "map.state")["payload"]
            assert board["here"]["id"] == location
            assert {t["id"] for t in board["around"]} == entities

    async def views(s):
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice([]), turn_id="t_scene_views", seat_id=None)
        return scene_views(ctx.world)

    live = run(settings, views)
    for _, location, entities in expected:
        # Сравниваем публикацию с новым подключением по локации группы.
        assert any(
            view["location"]["id"] == location and {e["id"] for e in view["entities"]} == entities for _, view in live
        )
    with connect(client, admin, cid) as (ws, snapshot):
        assert {e["id"] for e in snapshot["payload"]["scene"]["entities"]} == {ids["fountain"], ids["gob"]}
        ws.send_json({"type": "map.get", "payload": {}})
        board = next_of(ws, "map.state")["payload"]
        assert board["here"]["id"] == snapshot["payload"]["scene"]["location"]["id"]


def test_hidden_entity_stays_hidden_after_reconnect(client, admin, settings):
    cid, (p1, p2), (_, h2), ids = _split_party(client, admin, settings)

    async def hide(ctx):
        gob = ctx.world.entities[ids["gob"]]
        gob.state = {**(gob.state or {}), "hidden": True}
        ctx.world.scene.mode = "combat"
        ctx.world.scene.round = 1
        ctx.world.scene.turn_order = [
            {"id": gob.id, "initiative": 16},
            {"id": h2["id"], "initiative": 12},
        ]
        ctx.world.scene.state = {**(ctx.world.scene.state or {}), "turn": 0}

    _play(settings, cid, hide)
    for _ in range(2):
        with connect(client, p2, cid) as (ws, snapshot):
            assert ids["gob"] not in {e["id"] for e in snapshot["payload"]["scene"]["entities"]}
            assert ids["gob"] not in {e["id"] for e in snapshot["payload"]["scene"]["order"]}
            assert ids["gob"] not in {e["id"] for e in snapshot["payload"]["scene"]["turn_order"]}
            assert snapshot["payload"]["scene"]["turn"] is None
            ws.send_json({"type": "map.get", "payload": {}})
            board = next_of(ws, "map.state")["payload"]
            assert ids["gob"] not in {e["id"] for e in board["around"]}
            assert ids["gob"] not in {e["id"] for e in board["scene_view"]}

    # Владелец без кресла мастера также не получает скрытые объекты.
    with connect(client, admin, cid) as (_, snapshot):
        assert ids["gob"] not in {e["id"] for e in snapshot["payload"]["scene"]["entities"]}

    async def published(s):
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice([]), turn_id="t_hidden_views", seat_id=None)
        return scene_views(ctx.world)

    views = run(settings, published)
    assert any(seats is None for seats, _ in views)  # безопасная сцена для владельца без кресла
    for seats, scene in views:
        if seats is None or h2["seat_id"] in seats:
            assert ids["gob"] not in {e["id"] for e in scene["entities"]}
            assert ids["gob"] not in {e["id"] for e in scene["order"]}
            assert ids["gob"] not in {e["id"] for e in scene["turn_order"]}
            assert scene["turn"] is None


def test_each_hero_sees_own_place(client, admin, settings):
    cid, (p1, p2), (h1, h2), ids = _split_party(client, admin, settings)

    with connect(client, p1, cid) as (_, snap):
        scene = snap["payload"]["scene"]
        assert scene["location"]["id"] == ids["square"]
        assert {e["id"] for e in scene["entities"]} == {ids["fountain"]}
    with connect(client, p2, cid) as (_, snap):
        scene = snap["payload"]["scene"]
        assert scene["location"]["id"] == ids["docks"]
        assert {e["id"] for e in scene["entities"]} == {ids["gob"]}
    with connect(client, admin, cid) as (_, snap):  # владелец без героя видит оба места
        assert {e["id"] for e in snap["payload"]["scene"]["entities"]} == {ids["fountain"], ids["gob"]}

    async def views(s):
        from app.tools.runtime import open_context

        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice([]), turn_id="t_views", seat_id=None)
        return [(seats, v["location"]["id"], {e["id"] for e in v["entities"]}) for seats, v in scene_views(ctx.world)]

    out = run(settings, views)
    by_place = {loc: (seats, ents) for seats, loc, ents in out}
    assert by_place[ids["docks"]] == ([h2["seat_id"]], {ids["gob"]})
    # мастер и место без героя здесь получают общую сцену; места героев — свою
    assert any(h1["seat_id"] in (seats or []) for seats, loc, _ in out if loc == ids["square"])

    # герой вернулся: отряд снова вместе, одна сцена всем
    async def back(ctx):
        await _ok(ctx, "move", {"character_ids": [h2["id"]], "location_id": ids["square"]})
        return ctx.world.split, scene_views(ctx.world)

    split, views_ = _play(settings, cid, back)
    assert not split and len(views_) == 1 and views_[0][0] is None


# --- раздельный чат и очередь мастера (шаг 4б) ---


@pytest.fixture
def llm():
    return ScriptedLLM([])


@pytest.fixture
def game_client(settings, llm):
    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([]))) as c:
        yield c


@pytest.fixture
def admin_g(game_client):
    root = login(game_client, "root", "rootpass")
    ok(game_client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root), 201)
    return login(game_client, "Arty", "secret1")


def act(client, head, cid, text):
    """Игрок пишет действие и ждёт ответа мастера — в том числе ответа только своей части отряда."""
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": text}})
        for _ in range(40):
            e = ws.receive_json()
            if e["type"] == "message.new" and e["payload"]["kind"] == "narration":
                client.portal.call(client.app.state.master.wait_idle, cid)
                return e["payload"]
    raise AssertionError("мастер не ответил")


def _seen(client, head, cid):
    with connect(client, head, cid, last_seq=0) as (_, snap):
        return snap["payload"]["messages"]


# --- бой, время и звук по группам (шаг 4в) ---


def _fight(settings, cid, ids):
    """Бой в доках: Гимли и гоблин в очереди, Бран на площади вне боя."""

    async def go(ctx):
        await _ok(ctx, "set_scene_mode", {"mode": "combat"})
        return [x["id"] for x in ctx.world.scene.turn_order]

    return _play(settings, cid, go)


def test_group_clocks_catch_up_on_meeting(client, admin, settings):
    cid, _, (h1, h2), ids = _split_party(client, admin, settings)

    async def rest_on_square(s):
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice([]), turn_id="t_clock1", seat_id=None, focus=ids["square"])
        t0 = ctx.world.enter_clock()
        await _ok(ctx, "advance_time", {"amount": 8, "unit": "hour", "reason": "сон"})
        ctx.world.settle_clock(t0)
        await s.commit()
        return t0, ctx.world.scene.game_time, ctx.world.lags()

    t0, now_, lags = run(settings, rest_on_square)
    assert now_ == t0 + 8 * 3600 and lags == {h2["id"]: 8 * 3600}

    async def docks_turn(s):
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice([]), turn_id="t_clock2", seat_id=None, focus=ids["docks"])
        t1 = ctx.world.enter_clock()
        seen = ctx.world.scene.game_time  # ход доков идёт по их часам
        await _ok(ctx, "advance_time", {"amount": 1, "unit": "hour", "reason": "обыск"})
        ctx.world.settle_clock(t1)
        mid = (ctx.world.scene.game_time, ctx.world.lags())
        await _ok(ctx, "move", {"character_ids": [h2["id"]], "location_id": ids["square"]})
        late = ctx.world.catch_up()
        await s.commit()
        return seen, mid, late, ctx.world.lags()

    seen, mid, late, after = run(settings, docks_turn)
    assert seen == t0
    assert mid == (now_, {h2["id"]: 7 * 3600})  # часы кампании не ушли вперёд: доки отстают на 7 часов
    assert late == [(["Гимли"], 7 * 3600)] and after == {}


def test_each_group_hears_own_music(client, admin, settings):
    cid, _, (h1, h2), ids = _split_party(client, admin, settings)

    async def go(ctx):
        sc = ctx.world.scene
        sc.state = {**(sc.state or {}), "audio": {"v": 3}, "audio_at": {ids["docks"]: {"v": 9}}}
        views = audio.views(ctx.campaign, sc, ctx.world.groups())
        by_seat = {seat: st["v"] for seats, st in views for seat in seats}
        await _ok(ctx, "move", {"character_ids": [h2["id"]], "location_id": ids["square"]})
        audio.regroup(ctx)
        return by_seat, sc.state.get("audio_at"), sc.state["audio"]["v"]

    by_seat, at, v = _play(settings, cid, go)
    assert by_seat[h2["seat_id"]] == 9 and by_seat[h1["seat_id"]] == 3
    # встретились на площади: звучит то, что было на площади (общий звук), свой звук доков забыт
    assert at is None and v == 3


def test_live_master_answers_one_group(client, admin, settings):
    cid, (p1, p2), _, ids = _split_party(client, admin, settings, master={"type": "owner"})
    with connect(client, admin, cid) as (ws, snap):
        assert {p["id"] for p in snap["payload"]["scene"]["party"]} == {ids["square"], ids["docks"]}
        ws.send_json(
            {
                "type": "message.send",
                "payload": {"kind": "narration", "text": "Вода плещет о сваи.", "place": ids["docks"]},
            }
        )
        m = next_of(ws, "message.new")["payload"]
        assert m["whisper"] and m["data"]["place"] == ids["docks"]
    assert "Вода плещет о сваи." in {x["content"] for x in _seen(client, p2, cid)}
    assert "Вода плещет о сваи." not in {x["content"] for x in _seen(client, p1, cid)}
