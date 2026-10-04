# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Разделение отряда (design/party-split.md): мастер видит существ там, где стоит каждый герой, а игрок видит
окружение своего места."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.llm import ScriptedLLM
from app.db.models import Campaign, Message
from app.main import create_app
from app.tools.registry import execute
from app.tools.runtime import scene_views
from tests.conftest import login
from tests.game import FIGHTER, QueueDice, import_base, ok, party, run
from tests.test_map import _ok, _play
from tests.test_master import DONE
from tests.test_ws import connect, next_of


def _split_party(client, admin, settings):
    """Два героя на площади, второй уходит в доки; в доках гоблин, на площади фонтан."""
    import_base(settings)
    c, (p1, p2), h1 = party(client, admin, players=2)
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
