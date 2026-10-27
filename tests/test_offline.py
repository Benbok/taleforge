# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Офлайн и голосование (этап 8, ТЗ раздел 11): ожидание переподключения, голосование и его исходы, игра за
ушедшего, возврат героя со сводкой пропущенного, уход живого мастера, пропуск хода в бою."""

import time

from app.db.models import Campaign, Character, Message, Seat
from tests.game import add_hero, ok, party, run
from tests.test_api import invite, make_campaign, register
from tests.test_master import DONE, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_ws import connect, next_of

FAST = {"reconnect_grace_sec": 0.2, "vote_timeout_sec": 30, "away_skip_sec": 0}


def tune(settings, cid, **kw):
    async def go(s):
        c = await s.get(Campaign, cid)
        c.settings = {**c.settings, **FAST, **kw}
        await s.commit()

    run(settings, go)


def seat_of(snap, name):
    return next(s for s in snap["payload"]["seats"] if s["user_name"] == name)["id"]


def presence_until(ws, seat_id, status):
    for _ in range(40):
        e = next_of(ws, "presence.changed")
        if e["payload"]["seat_id"] == seat_id and e["payload"]["status"] == status:
            return
    raise AssertionError(f"нет статуса {status}")


def narration(ws):
    for _ in range(40):
        e = next_of(ws, "message.new")["payload"]
        if e["kind"] == "narration" or "повторите" in e["content"]:
            return e["content"]
    raise AssertionError("нет ответа мастера")


def two_players(client, admin, settings, **kw):
    """Две героя у двух игроков, мастер — ИИ, сессия идёт."""
    c, (p1, p2), hero = party(client, admin, players=2, start=False, **kw)

    add_hero(client, c["id"], p2, "Торин")
    ok(client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin))
    tune(settings, c["id"])
    return c, p1, p2, hero


def test_reconnect_within_grace_is_not_a_leave(game_client, admin_g, settings):
    c, p1, p2, _ = two_players(game_client, admin_g, settings)
    tune(settings, c["id"], reconnect_grace_sec=30)
    with connect(game_client, p2, c["id"]) as (w2, snap):
        arag = seat_of(snap, "Арагорн")
        with connect(game_client, p1, c["id"]):
            presence_until(w2, arag, "online")
        presence_until(w2, arag, "reconnecting")
        with connect(game_client, p1, c["id"]) as (_, again):
            assert seat_of(again, "Арагорн") == arag
            presence_until(w2, arag, "online")
        assert game_client.app.state.presence.votes(c["id"]) == []


def test_tie_or_timeout_pauses(game_client, admin_g, settings):
    c, p1, p2, _ = two_players(game_client, admin_g, settings)
    tune(settings, c["id"], vote_timeout_sec=0.3)
    with connect(game_client, p2, c["id"]) as (w2, snap):
        arag = seat_of(snap, "Арагорн")
        with connect(game_client, p1, c["id"]):
            pass
        presence_until(w2, arag, "offline")
        next_of(w2, "vote.started")
        ended = next_of(w2, "vote.ended")["payload"]
        assert ended["outcome"] == "pause"
        assert next_of(w2, "session.paused")["payload"]["status"] == "paused"
    assert run(settings, lambda s: s.get(Campaign, c["id"])).status == "paused"


def test_return_during_vote_cancels_it(game_client, admin_g, settings):
    c, p1, p2, _ = two_players(game_client, admin_g, settings)
    with connect(game_client, p2, c["id"]) as (w2, snap):
        arag = seat_of(snap, "Арагорн")
        with connect(game_client, p1, c["id"]):
            pass
        next_of(w2, "vote.started")
        with connect(game_client, p1, c["id"]) as (w1, back):
            assert back["payload"]["votes"] == [] or back["payload"]["votes"][0]["seat_id"] == arag
            assert next_of(w2, "vote.ended")["payload"]["outcome"] == "canceled"
            # вернулся раньше, чем что-то пропустил: сводки нет
    assert game_client.app.state.presence.votes(c["id"]) == []
    assert run(settings, lambda s: s.get(Campaign, c["id"])).status == "active"


def test_everyone_gone_pauses_without_vote(game_client, admin_g, settings):
    c, p1, p2, _ = two_players(game_client, admin_g, settings)
    with connect(game_client, p1, c["id"]):
        pass
    with connect(game_client, p2, c["id"]):
        pass
    deadline = time.time() + 5
    while time.time() < deadline and run(settings, lambda s: s.get(Campaign, c["id"])).status != "paused":
        time.sleep(0.1)
    assert run(settings, lambda s: s.get(Campaign, c["id"])).status == "paused"
    texts = [m.content for m in rows(settings, Message, Message.campaign_id == c["id"], Message.kind == "system")]
    assert "Игроков в сети не осталось: сессия на паузе." in texts


def test_manual_pause_returns_heroes(game_client, admin_g, settings):
    c, p1, p2, hero = two_players(game_client, admin_g, settings)
    with connect(game_client, p2, c["id"]) as (w2, snap):
        arag, gimli = seat_of(snap, "Арагорн"), seat_of(snap, "Гимли")
        with connect(game_client, p1, c["id"]):
            pass
        vote = next_of(w2, "vote.started")["payload"]
        w2.send_json({"type": "vote.cast", "payload": {"vote_id": vote["vote_id"], "option": f"seat:{gimli}"}})
        next_of(w2, "stand_in.changed")
        ok(game_client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin_g))
        next_of(w2, "session.paused")
    seat = run(settings, lambda s: s.get(Seat, arag))
    assert seat.stand_in_user_id is None
    ch = run(settings, lambda s: s.get(Character, hero["id"]))
    assert ch.seat_id == arag


def test_lobby_leave_is_plain_offline(client, admin):
    c = make_campaign(client, admin, players=2)
    inv = invite(client, admin, c["id"])
    p1 = register(client, inv["token"], "Арагорн")
    p2 = register(client, inv["token"], "Гимли")
    with connect(client, p2, c["id"]) as (w2, snap):
        arag = seat_of(snap, "Арагорн")
        assert snap["payload"]["votes"] == [] and snap["payload"]["me"]["stand_in_for"] == []
        with connect(client, p1, c["id"]):
            pass
        presence_until(w2, arag, "offline")
