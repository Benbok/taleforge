"""Ожидающая реплика при ИИ-мастере: одна на игрока, отмена и статус
(docs/superpowers/specs/2026-09-28-pending-replies-design.md).
"""

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import ScriptedLLM
from app.db.models import MasterTurn, Message
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


def withdraw(ws, mid):
    ws.send_json({"type": "message.withdraw", "payload": {"message_id": mid}})
    for _ in range(20):
        e = ws.receive_json()
        if e["type"] in ("message.withdrawn", "message.rejected") and (
            "text" in e["payload"] or e["type"] == "message.rejected"
        ):
            return e
    raise AssertionError("нет ответа на отмену")


def test_withdraw_own_pending(client, admin, settings):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        m = say(ws, "Лезу на стену")["payload"]
        e = withdraw(ws, m["id"])
        assert e["payload"] == {"id": m["id"], "seq": m["seq"], "text": "Лезу на стену"}
        assert say(ws, "Прыгаю на уступ")["type"] == "message.new"  # ограничение снято
    assert run(settings, lambda s: s.get(Message, m["id"])) is None
    with connect(client, p1, c["id"], last_seq=0) as (_, snap):  # досылка не возвращает отменённое
        assert m["id"] not in {x["id"] for x in snap["payload"]["messages"]}


def test_others_see_withdrawn(client, admin):
    c, (p1, p2), _ = party(client, admin, players=2)
    with connect(client, p2, c["id"]) as (ws2, _):
        with connect(client, p1, c["id"]) as (ws1, _):
            m = say(ws1, "Лезу на стену")["payload"]
            withdraw(ws1, m["id"])
        e = next_of(ws2, "message.withdrawn")
        assert e["payload"] == {"id": m["id"], "seq": m["seq"]}


def test_withdraw_refused_for_taken_and_foreign(client, admin, settings):
    c, (p1, p2), _ = party(client, admin, players=2)
    with connect(client, p1, c["id"]) as (ws1, _):
        m = say(ws1, "Лезу на стену")["payload"]
        with connect(client, p2, c["id"]) as (ws2, _):
            e = withdraw(ws2, m["id"])
            assert e["type"] == "message.rejected" and e["payload"]["reason"] == "Эту реплику отменить нельзя."
            assert withdraw(ws2, "m_nope")["payload"]["reason"] == "Эту реплику отменить нельзя."
        add_turn(settings, c["id"], m["seq"], "running")
        e = withdraw(ws1, m["id"])
        assert e["type"] == "message.rejected" and e["payload"]["reason"] == "Мастер уже отвечает на эту реплику."


def test_withdraw_in_combat_clears_submitted(client, admin, settings):
    from app.db.models import Scene

    c, (p1,), hero = party(client, admin)

    async def fight(s):
        sc = await s.get(Scene, c["id"])
        sc.mode, sc.turn_order, sc.state = "combat", [{"id": hero["id"], "initiative": 10}], {"turn": 0}
        await s.commit()

    run(settings, fight)
    with connect(client, p1, c["id"]) as (ws, _):
        m = say(ws, "Бью мечом")["payload"]
        assert run(settings, lambda s: s.get(Scene, c["id"])).state["submitted"] is True
        withdraw(ws, m["id"])
    assert run(settings, lambda s: s.get(Scene, c["id"])).state["submitted"] is False


def test_speech_in_combat_does_not_block_action(client, admin, settings):
    # в бою ход мастера запускает только действие героя, чей ход: речь и шёпот до него не должны запирать действие
    from app.db.models import Scene

    c, (p1,), hero = party(client, admin)

    async def fight(s):
        sc = await s.get(Scene, c["id"])
        sc.mode, sc.turn_order, sc.state = "combat", [{"id": hero["id"], "initiative": 10}], {"turn": 0}
        await s.commit()

    run(settings, fight)
    with connect(client, p1, c["id"]) as (ws, _):
        assert say(ws, "Сдавайтесь!", kind="speech")["type"] == "message.new"
        assert say(ws, "мастер, тут есть ловушки?", kind="whisper")["type"] == "message.new"
        ws.send_json({"type": "actions.get", "payload": {}})
        st = next_of(ws, "state.actions")["payload"]
        assert "chat.play" in st["actions"] and "chat.whisper" in st["actions"] and st["pending"] is None
        assert say(ws, "Бью мечом")["type"] == "message.new"
        # второе действие за ход по-прежнему отклоняет боевое правило
        again = say(ws, "И ещё раз")["payload"]
        assert again["reason"] == "Действие на этот ход уже заявлено: дождитесь ответа мастера."


DONE = {"text": "готово"}


def test_turn_publishes_states(settings, llm):
    import_base(settings)
    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([]))) as c:
        root = login(c, "root", "rootpass")
        ok(c.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root), 201)
        adm = login(c, "Arty", "secret1")
        camp, (p1,), _ = party(c, adm)
        llm.replies += [DONE, DONE, {"text": "Стена оказалась скользкой."}]
        with connect(c, p1, camp["id"]) as (ws, _):
            m = say(ws, "Лезу на стену")["payload"]
            states = []
            for _ in range(40):
                e = ws.receive_json()
                if e["type"] == "message.state":
                    states.append((e["payload"]["ids"], e["payload"]["state"]))
                if len(states) == 2:
                    break
            c.portal.call(c.app.state.master.wait_idle, camp["id"])
    assert states == [([m["id"]], "processing"), ([m["id"]], "answered")]


def test_empty_batch_is_skipped_without_model(client, admin, settings, llm):
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        m = say(ws, "Лезу на стену")["payload"]
        withdraw(ws, m["id"])

    async def turn(s):
        t = MasterTurn(campaign_id=c["id"], upto_seq=m["seq"], trace={"from_seq": m["seq"]})
        s.add(t)
        await s.commit()
        return t.id

    tid = run(settings, turn)

    async def play():
        async with client.app.state.sessionmaker() as s:
            return await client.app.state.master._play(s, c["id"], tid, [])

    out = client.portal.call(play)
    assert out["skipped"] and out["messages"] == [] and llm.requests == []
    assert run(settings, lambda s: s.get(MasterTurn, tid)).status == "skipped"


