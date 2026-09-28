from contextlib import contextmanager

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.test_api import invite, make_campaign, register


def token_of(headers):
    return headers["Authorization"].split()[1]


@contextmanager
def connect(client, headers, campaign_id, last_seq=None):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "payload": {"token": token_of(headers)}})
        assert ws.receive_json()["type"] == "auth.ok"
        ws.send_json({"type": "campaign.join", "payload": {"campaign_id": campaign_id, "last_seq": last_seq}})
        snap = ws.receive_json()
        assert snap["type"] == "state.snapshot", snap
        yield ws, snap


def next_of(ws, type_):
    for _ in range(20):
        e = ws.receive_json()
        if e["type"] == type_:
            return e
    raise AssertionError(f"нет события {type_}")


def presence_of(ws, seat_id):
    while True:
        e = next_of(ws, "presence.changed")
        if e["payload"]["seat_id"] == seat_id:
            return e["payload"]["status"]


def setup(client, admin, players=2, master=None):
    c = make_campaign(client, admin, players=players, **({"master": master} if master else {}))
    inv = invite(client, admin, c["id"])
    p1 = register(client, inv["token"], "Арагорн")
    p2 = register(client, inv["token"], "Гимли")
    return c, p1, p2


def test_rejects_bad_token(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "payload": {"token": "junk"}})
        assert ws.receive_json()["payload"]["code"] == "unauthorized"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_join_requires_access(client, admin, root):
    c = make_campaign(client, admin)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "payload": {"token": token_of(root)}})
        ws.receive_json()
        ws.send_json({"type": "campaign.join", "payload": {"campaign_id": c["id"]}})
        assert ws.receive_json()["payload"]["code"] == "not_found"


def test_chat_whisper_and_replay(client, admin):
    c, p1, p2 = setup(client, admin, master={"type": "owner"})
    client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin)

    with (
        connect(client, p1, c["id"]) as (w1, snap1),
        connect(client, p2, c["id"]) as (w2, _),
        connect(client, admin, c["id"]) as (wm, _),
    ):
        assert snap1["payload"]["me"]["role"] == "player"
        assert any(m["kind"] == "system" for m in snap1["payload"]["messages"])

        w1.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Осматриваю дверь"}})
        e = next_of(w2, "message.new")
        assert e["payload"]["content"] == "Осматриваю дверь" and e["payload"]["author"] == "Арагорн"
        seq_seen = e["seq"]

        w1.send_json({"type": "message.send", "payload": {"kind": "whisper", "text": "Прячу кольцо"}})
        assert next_of(wm, "message.new")["payload"]["content"] == "Осматриваю дверь"
        assert next_of(wm, "message.new")["payload"]["whisper"] is True  # мастер видит
        assert next_of(w1, "message.new")["payload"]["content"] == "Осматриваю дверь"
        assert next_of(w1, "message.new")["payload"]["content"] == "Прячу кольцо"  # автор видит

        w1.send_json({"type": "message.send", "payload": {"kind": "speech", "text": "// перерыв на чай"}})
        ooc = next_of(w2, "message.new")
        assert ooc["payload"]["kind"] == "ooc" and ooc["payload"]["content"] == "перерыв на чай"  # шёпот не пришёл

    # Досылка после переподключения: шёпота в ней нет
    with connect(client, p2, c["id"], last_seq=seq_seen - 1) as (_, snap):
        contents = [m["content"] for m in snap["payload"]["messages"]]
        assert snap["payload"]["replay"] is True
        assert contents == ["Осматриваю дверь", "перерыв на чай"]


def test_rules_for_message_kinds(client, admin):
    c, p1, _ = setup(client, admin)
    with connect(client, p1, c["id"]) as (w1, _):
        w1.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Иду"}})
        assert "сессия не запущена" in next_of(w1, "message.rejected")["payload"]["reason"]
        w1.send_json({"type": "message.send", "payload": {"kind": "ooc", "text": "привет"}})
        assert next_of(w1, "message.new")["payload"]["kind"] == "ooc"
        client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin)
        w1.send_json({"type": "message.send", "payload": {"kind": "narration", "text": "Я мастер"}})
        assert next_of(w1, "message.rejected")["payload"]["reason"].startswith("игрок пишет")
        w1.send_json({"type": "message.send", "payload": {"kind": "action", "text": "x" * 5000}})
        assert "длиннее" in next_of(w1, "message.rejected")["payload"]["reason"]
        w1.send_json({"type": "vote.cast", "payload": {}})
        assert next_of(w1, "error")["payload"]["code"] == "not_implemented"
        w1.send_json({"type": "ping"})
        assert next_of(w1, "pong")["type"] == "pong"


def test_owner_without_seat_only_ooc(client, admin):
    c, *_ = setup(client, admin)  # мастер — агент, владелец без места
    client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin)
    with connect(client, admin, c["id"]) as (wo, snap):
        assert snap["payload"]["me"]["seat_id"] is None and snap["payload"]["me"]["is_owner"]
        wo.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Хочу играть"}})
        assert next_of(wo, "message.rejected")


def test_presence(client, admin):
    c, p1, p2 = setup(client, admin)
    with connect(client, p2, c["id"]) as (w2, _):
        with connect(client, p1, c["id"]) as (_, snap):
            arag = next(s for s in snap["payload"]["seats"] if s["user_name"] == "Арагорн")
            assert arag["presence"] == "online"
            assert presence_of(w2, arag["id"]) == "online"
        assert presence_of(w2, arag["id"]) == "offline"
