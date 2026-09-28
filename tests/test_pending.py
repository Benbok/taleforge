"""Ожидающая реплика при ИИ-мастере: одна на игрока, отмена и статус
(docs/superpowers/specs/2026-09-28-pending-replies-design.md).
"""

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import ScriptedLLM
from app.db.models import MasterTurn, Message  # noqa: F401
from app.main import create_app
from tests.conftest import login
from tests.game import QueueDice, import_base, ok, party, run
from tests.test_ws import connect, next_of

REASON = "Ваша реплика ждёт мастера. Отмените её, чтобы написать другую, или пишите вне игры через //."


@pytest.fixture
def llm():
    return ScriptedLLM([])


@pytest.fixture
def client(settings, llm):
    import_base(settings)
    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([]))) as c:
        c.app.state.master.notify = lambda cid: None  # мастер сам ход не начинает: реплика остаётся ожидающей
        yield c


@pytest.fixture
def admin(client):
    root = login(client, "root", "rootpass")
    ok(client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root), 201)
    return login(client, "Arty", "secret1")


def say(ws, text, kind="auto"):
    ws.send_json({"type": "message.send", "payload": {"kind": kind, "text": text}})
    for _ in range(20):
        e = ws.receive_json()
        if e["type"] in ("message.new", "message.rejected"):
            return e
    raise AssertionError("нет ответа на реплику")


def add_turn(settings, cid, upto, status):
    async def go(s):
        s.add(MasterTurn(campaign_id=cid, upto_seq=upto, status=status, trace={"from_seq": upto}))
        await s.commit()

    run(settings, go)


def test_second_reply_rejected_while_first_waits(client, admin):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        first = say(ws, "Лезу на стену")
        assert first["type"] == "message.new" and first["payload"]["state"] == "pending"
        second = say(ws, "А нет, прыгаю на уступ")
        assert second["type"] == "message.rejected" and second["payload"]["reason"] == REASON
        whisper = say(ws, "мастер, тут есть ловушки?", kind="whisper")
        assert whisper["type"] == "message.rejected"
        ooc = say(ws, "// пойду за чаем")
        assert ooc["type"] == "message.new" and ooc["payload"]["kind"] == "ooc" and ooc["payload"]["state"] is None


def test_next_reply_allowed_once_turn_took_it(client, admin, settings):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        first = say(ws, "Лезу на стену")
        add_turn(settings, c["id"], first["payload"]["seq"], "running")
        nxt = say(ws, "Оглядываюсь с вершины")
        assert nxt["type"] == "message.new" and nxt["payload"]["state"] == "pending"


def test_no_limit_with_human_master(client, admin):
    c, (p1,), _ = party(client, admin, master={"type": "owner"})
    with connect(client, p1, c["id"]) as (ws, _):
        assert say(ws, "Лезу на стену")["payload"]["state"] is None
        assert say(ws, "Прыгаю на уступ")["type"] == "message.new"


def test_actions_block_play_and_offer_withdraw(client, admin):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, snap):
        assert "chat.play" in snap["payload"]["actions"] and snap["payload"]["pending"] is None
        assert snap["payload"]["collect_window_sec"] == 0  # party() создаёт кампанию с окном 0
        m = say(ws, "Лезу на стену")["payload"]
        ws.send_json({"type": "actions.get", "payload": {}})
        st = next_of(ws, "state.actions")["payload"]
        assert "chat.play" not in st["actions"] and "chat.whisper" not in st["actions"]
        assert st["blocked"]["chat.play"] == REASON and st["blocked"]["chat.whisper"] == REASON
        assert "chat.withdraw" in st["actions"] and "chat.ooc" in st["actions"]
        assert st["pending"]["id"] == m["id"]


def test_states_in_snapshot(client, admin, settings):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        a = say(ws, "Лезу на стену")["payload"]
    add_turn(settings, c["id"], a["seq"], "done")
    # ход боя (advance) пишет тот же upto_seq позже: статус берётся от первого хода
    add_turn(settings, c["id"], a["seq"], "running")
    with connect(client, p1, c["id"]) as (ws, _):
        b = say(ws, "Спускаюсь")["payload"]
    add_turn(settings, c["id"], b["seq"], "failed")
    with connect(client, p1, c["id"]) as (ws, _):
        d = say(ws, "Иду к воротам")["payload"]
    with connect(client, p1, c["id"]) as (_, snap):
        states = {m["id"]: m["state"] for m in snap["payload"]["messages"]}
    assert states[a["id"]] == "answered" and states[b["id"]] == "failed" and states[d["id"]] == "pending"
    sys = [m for m in snap["payload"]["messages"] if m["kind"] == "system"]
    assert all(m["state"] is None for m in sys)


def test_no_pending_state_when_session_paused(client, admin):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        a = say(ws, "Лезу на стену")["payload"]
    ok(client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin))
    with connect(client, p1, c["id"]) as (_, snap):
        states = {m["id"]: m["state"] for m in snap["payload"]["messages"]}
        assert states[a["id"]] is None and snap["payload"]["pending"] is None
