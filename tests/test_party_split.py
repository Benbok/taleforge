# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Разделение отряда (design/party-split.md): мастер видит существ там, где стоит каждый герой, а игрок видит
окружение своего места."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents import memory
from app.agents.llm import ScriptedLLM
from app.core import audio, combat
from app.db.models import Campaign, Message
from app.main import create_app
from app.tools.registry import execute
from app.tools.runtime import open_context, scene_views
from tests.conftest import login
from tests.game import FIGHTER, QueueDice, import_base, ok, party, run
from tests.test_map import _ok, _play
from tests.test_master import DONE
from tests.test_ws import connect, next_of


def _split_party(client, admin, settings, **kw):
    """Два героя на площади, второй уходит в доки; в доках гоблин, на площади фонтан."""
    import_base(settings)
    c, (p1, p2), h1 = party(client, admin, players=2, **kw)
    cid = c["id"]
    h2 = ok(client.post(f"/api/campaigns/{cid}/characters", json={**FIGHTER, "name": "Гимли"}, headers=p2), 201)
    ok(client.post(f"/api/campaigns/{cid}/characters/{h2['id']}/submit", headers=p2))

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
    return cid, (p1, p2), (h1, h2), ids


def test_master_sees_every_place_of_split_party(client, admin, settings):
    cid, _, (h1, h2), ids = _split_party(client, admin, settings)

    async def check(ctx):
        w = ctx.world
        table = w.scene_table()
        assert "отряд разделён" in table
        assert f"МЕСТО {ids['docks']} Доки: здесь Гимли" in table and f"МЕСТО {ids['square']} Площадь" in table
        # гоблин в доках — допустимая цель, хотя сцена осталась на площади
        assert ids["gob"] in w.valid_ids()["entities"] and w.scene.location_id == ids["square"]
        far = await execute(
            ctx, "resolve_attack", {"attacker_id": h1["id"], "target_id": ids["gob"], "attack": "unarmed"}
        )
        assert not far["ok"] and "в разных местах" in far["error"]
        # бой по умолчанию — только там, где враги
        await _ok(ctx, "set_scene_mode", {"mode": "combat"})
        return {x["id"] for x in w.scene.turn_order}

    assert _play(settings, cid, check) == {h2["id"], ids["gob"]}


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
    cid, (p1, p2), (_, _), ids = _split_party(client, admin, settings)

    async def hide(ctx):
        gob = ctx.world.entities[ids["gob"]]
        gob.state = {**(gob.state or {}), "hidden": True}

    _play(settings, cid, hide)
    for _ in range(2):
        with connect(client, p2, cid) as (ws, snapshot):
            assert ids["gob"] not in {e["id"] for e in snapshot["payload"]["scene"]["entities"]}
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
    for seats, scene in views:
        if p2["seat_id"] in (seats or []):
            assert ids["gob"] not in {e["id"] for e in scene["entities"]}


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
    assert any(h1["seat_id"] in seats for seats, loc, _ in out if loc == ids["square"])

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


def test_split_party_has_own_chat_and_meets_again(game_client, admin_g, llm, settings):
    cid, (p1, p2), (h1, h2), ids = _split_party(game_client, admin_g, settings)
    llm.replies += [DONE, DONE, {"text": "В доках пахнет тиной."}]
    n = act(game_client, p2, cid, "Осматриваю доки")
    assert n["content"] == "В доках пахнет тиной." and n["whisper"]  # ответ только части отряда

    decide = llm.requests[0]["messages"][1]["content"]
    assert "этот ход — только для героев выше" in decide and "Бран — Площадь" in decide
    assert "Фонтан" not in decide and "Гоблин" in decide  # окружение только своего места

    mine = {m["content"] for m in _seen(game_client, p2, cid)}
    theirs = {m["content"] for m in _seen(game_client, p1, cid)}
    assert {"Осматриваю доки", "В доках пахнет тиной."} <= mine
    assert not {"Осматриваю доки", "В доках пахнет тиной."} & theirs
    # сводка кампании для памяти мастера помнит и то, что было порознь
    remembered = run(settings, lambda s: memory.public_messages(s, cid, 0))
    assert "В доках пахнет тиной." in {m.content for m in remembered}

    # Бран приходит в доки: встреча видна обоим, мастер пересказывает, что было с Гимли
    llm.replies += [
        {"tool_calls": [("move", {"character_ids": [h1["id"]], "location_id": ids["docks"]})]},
        DONE,
        {"text": "Двое встречаются у причала."},
    ]
    n = act(game_client, p1, cid, "Иду в доки")
    assert n["content"] == "Двое встречаются у причала." and not n["whisper"]
    narrate = llm.requests[-1]["messages"][-1]["content"]
    assert "Встреча: к героям присоединились Гимли" in narrate and "В доках пахнет тиной." in narrate
    seen2 = [m["content"] for m in _seen(game_client, p2, cid)]
    assert "Двое встречаются у причала." in seen2 and "Отряд снова вместе." in seen2

    async def taken(s):
        return [
            (m.content, m.turn_id is not None) for m in await s.scalars(select(Message).where(Message.kind == "action"))
        ]

    assert all(t for _, t in run(settings, taken))


def test_groups_are_answered_separately(game_client, admin_g, llm, settings):
    """Реплики двух частей отряда — два хода: каждой свой ответ, без ожидания другой группы."""
    cid, (p1, p2), _, _ = _split_party(game_client, admin_g, settings)
    game_client.app.state.master.notify = lambda c: None  # ходы запускаем сами

    with connect(game_client, p1, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Пью из фонтана"}})
        next_of(ws, "message.new")
    with connect(game_client, p2, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Прячусь за бочкой"}})
        next_of(ws, "message.new")

    llm.replies += [DONE, DONE, {"text": "Вода холодная."}, DONE, DONE, {"text": "Бочка пахнет рыбой."}]
    master = game_client.app.state.master
    first = game_client.portal.call(master.run_turn, cid)
    second = game_client.portal.call(master.run_turn, cid)
    game_client.portal.call(master.wait_idle, cid)
    assert first and second and first != second
    assert "Пью из фонтана" in llm.requests[0]["messages"][1]["content"]
    assert "Прячусь за бочкой" not in llm.requests[0]["messages"][1]["content"]
    assert "Прячусь за бочкой" in llm.requests[3]["messages"][1]["content"]
    assert "Вода холодная." not in {m["content"] for m in _seen(game_client, p2, cid)}


# --- бой, время и звук по группам (шаг 4в) ---


def _fight(settings, cid, ids):
    """Бой в доках: Гимли и гоблин в очереди, Бран на площади вне боя."""

    async def go(ctx):
        await _ok(ctx, "set_scene_mode", {"mode": "combat"})
        return [x["id"] for x in ctx.world.scene.turn_order]

    return _play(settings, cid, go)


def test_fight_is_only_where_the_foes_are(client, admin, settings):
    cid, (p1, p2), (h1, h2), ids = _split_party(client, admin, settings)
    assert set(_fight(settings, cid, ids)) == {h2["id"], ids["gob"]}

    # Бран вне боя: у него свободный режим, хода нет, писать можно как обычно
    with connect(client, p1, cid) as (ws, snap):
        scene = snap["payload"]["scene"]
        assert scene["mode"] == "free" and scene["turn"] is None and snap["payload"]["turn"] is None
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Пью из фонтана"}})
        assert next_of(ws, "message.new")["payload"]["content"] == "Пью из фонтана"
    with connect(client, p2, cid) as (_, snap):
        assert snap["payload"]["scene"]["mode"] == "combat" and snap["payload"]["turn"] is not None

    async def target(ctx):
        gob = ctx.world.actor(ids["gob"])
        return combat._pick_target(ctx, gob).id, combat.turn_views(ctx.world)

    tgt, views = _play(settings, cid, target)
    assert tgt == h2["id"]  # гоблин бьёт только тех, кто рядом
    calm = next(seats for seats, turn in views if turn is None)
    assert calm == [h1["seat_id"]]

    async def rest(s):  # Бран вне боя может отдохнуть, Гимли — нет
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice([]), turn_id="t_rest", seat_id=None, focus=ids["square"])
        calm = await execute(ctx, "rest", {"character_ids": [h1["id"]], "kind": "short"})
        busy = await execute(ctx, "rest", {"character_ids": [h2["id"]], "kind": "short"})
        return calm["ok"], busy.get("error", "")

    calm_ok, busy = run(settings, rest)
    assert calm_ok and "в бою не отдыхают" in busy


def test_hero_joins_and_leaves_a_fight_by_moving(client, admin, settings):
    cid, _, (h1, h2), ids = _split_party(client, admin, settings)
    _fight(settings, cid, ids)

    async def join(ctx):
        r = await _ok(ctx, "move", {"character_ids": [h1["id"]], "location_id": ids["docks"]})
        return r, [x["id"] for x in ctx.world.scene.turn_order]

    r, order = _play(settings, cid, join)
    assert "Бран" in r["joined_combat"][0] and set(order) == {h1["id"], h2["id"], ids["gob"]}

    async def leave(ctx):
        cur = combat.current_id(ctx)
        r = await _ok(ctx, "move", {"character_ids": [h1["id"]], "location_id": ids["square"]})
        return r, [x["id"] for x in ctx.world.scene.turn_order], cur, combat.current_id(ctx)

    r, order, cur, now_ = _play(settings, cid, leave)
    assert r["left_combat"] == ["Бран"] and h1["id"] not in order
    assert now_ == cur or cur == h1["id"]  # чужой ход не сбился


def test_fronts_end_separately(client, admin, settings):
    """Бой в двух местах: конец боя в одном не заканчивает бой в другом."""
    cid, _, (h1, h2), ids = _split_party(client, admin, settings)

    async def go(ctx):
        rat = await _ok(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Второй гоблин", "location_id": ids["square"]},
        )
        await _ok(ctx, "set_scene_mode", {"mode": "combat"})
        assert len(combat.active_fronts(ctx)) == 2
        await _ok(ctx, "update_entity", {"entity_id": ids["gob"], "fled": True})
        notes = []
        ended = await combat.close_fronts(ctx, notes)
        return ended, notes, [x["id"] for x in ctx.world.scene.turn_order], rat["spawned"][0]["id"]

    ended, notes, order, rat = _play(settings, cid, go)
    assert not ended and "бой в месте «Доки» окончен: врагов не осталось" in notes
    assert {h1["id"], rat} <= set(order) and h2["id"] not in order  # Гимли вышел из боя, на площади бой идёт


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
