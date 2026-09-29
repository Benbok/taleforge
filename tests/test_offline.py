# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Офлайн и голосование (этап 8, ТЗ раздел 11): ожидание переподключения, голосование и его исходы, игра за
ушедшего, возврат героя со сводкой пропущенного, уход живого мастера, пропуск хода в бою."""

import time

from app.db.models import Campaign, Character, Event, LlmCall, Message, Seat
from tests.game import ok, party, run
from tests.test_api import invite, make_campaign, register
from tests.test_combat import _setup
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
    c, (p1, p2), hero = party(client, admin, players=2, **kw)
    from tests.game import FIGHTER

    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json={**FIGHTER, "name": "Торин"}, headers=p2), 201)
    ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=p2))
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


def test_vote_hands_hero_to_other_player_and_back(game_client, admin_g, settings, llm):
    c, p1, p2, hero = two_players(game_client, admin_g, settings)
    with connect(game_client, p2, c["id"]) as (w2, snap):
        arag = seat_of(snap, "Арагорн")
        with connect(game_client, p1, c["id"]):
            pass
        presence_until(w2, arag, "offline")
        vote = next_of(w2, "vote.started")["payload"]
        gimli = seat_of(snap, "Гимли")
        assert vote["seat_id"] == arag and vote["hero"] == "Бран" and vote["voters"] == [gimli]
        assert [o["id"] for o in vote["options"]] == [f"seat:{gimli}", "pause"]

        w2.send_json({"type": "vote.cast", "payload": {"vote_id": "нет такого", "option": "pause"}})
        assert next_of(w2, "error")["payload"]["code"] == "vote_rejected"
        # один оставшийся игрок решает сам
        w2.send_json({"type": "vote.cast", "payload": {"vote_id": vote["vote_id"], "option": f"seat:{gimli}"}})
        ended = next_of(w2, "vote.ended")["payload"]
        assert ended["outcome"] == f"seat:{gimli}"
        assert next_of(w2, "stand_in.changed")["payload"] == {
            "seat_id": arag,
            "stand_in": {"user_id": snap["payload"]["me"]["user_id"], "name": "Гимли"},
        }

        # лист героя ушедшего — без личной предыстории
        sheet = ok(game_client.get(f"/api/campaigns/{c['id']}/characters/{hero['id']}", headers=p2))
        assert sheet["stand_in"] and "private_backstory" not in sheet and sheet["sheet"]["abilities"]

        # Гимли ведёт Брана: реплика от места Арагорна
        llm.replies += [DONE, DONE, {"text": "Бран осторожно идёт вперёд."}]
        w2.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Бран идёт", "as_seat": arag}})
        m = next_of(w2, "message.new")["payload"]
        assert m["seat_id"] == arag and m["content"] == "Бран идёт"
        assert narration(w2).endswith("осторожно идёт вперёд.")
        game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
        # чужим героем без голосования не сыграть
        w2.send_json({"type": "message.send", "payload": {"kind": "action", "text": "x", "as_seat": gimli + "z"}})
        assert "не ведёте" in next_of(w2, "message.rejected")["payload"]["reason"]

        # Арагорн вернулся: герой снова его, и ему — сводка пропущенного, только ему
        llm.replies.append({"text": "Гимли повёл Брана вперёд по коридору."})
        with connect(game_client, p1, c["id"]) as (w1, back):
            assert back["payload"]["me"]["seat_id"] == arag
            assert next_of(w2, "stand_in.changed")["payload"] == {"seat_id": arag, "stand_in": None}
            for _ in range(30):
                e = next_of(w1, "message.new")["payload"]
                if e["content"].startswith("Пока вас не было"):
                    break
            assert "Гимли повёл Брана" in e["content"]
            game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])

    msgs = rows(settings, Message, Message.campaign_id == c["id"], Message.content.like("Пока вас не было%"))
    assert msgs[0].visible_to == [arag]
    calls = rows(settings, LlmCall, LlmCall.campaign_id == c["id"], LlmCall.purpose == "catchup")
    assert len(calls) == 1
    seat = run(settings, lambda s: s.get(Seat, arag))
    assert seat.stand_in_user_id is None


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


def test_live_master_leaves_ai_takes_over_and_gives_back(game_client, admin_g, settings, llm):
    c, (p1,), _ = party(game_client, admin_g, master={"type": "owner"})
    tune(settings, c["id"])
    with connect(game_client, p1, c["id"]) as (w1, snap):
        master = snap["payload"]["seats"][0]["id"]
        with connect(game_client, admin_g, c["id"]):
            pass
        presence_until(w1, master, "offline")
        vote = next_of(w1, "vote.started")["payload"]
        assert vote["subject"] == "master" and [o["id"] for o in vote["options"]] == ["ai_master", "pause"]
        w1.send_json({"type": "vote.cast", "payload": {"vote_id": vote["vote_id"], "option": "ai_master"}})
        assert next_of(w1, "vote.ended")["payload"]["outcome"] == "ai_master"
        assert next_of(w1, "stand_in.changed")["payload"]["stand_in"]["ai"] is True
        seat = run(settings, lambda s: s.get(Seat, master))
        assert seat.occupant_type == "agent" and seat.agent_config_id and seat.delegated_from == seat.user_id

        llm.replies += [DONE, DONE, {"text": "ИИ-мастер описывает зал."}]
        w1.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Осматриваюсь"}})
        assert narration(w1) == "ИИ-мастер описывает зал."
        game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])

        with connect(game_client, admin_g, c["id"]) as (_, back):
            assert back["payload"]["me"]["role"] == "master"
            assert next_of(w1, "stand_in.changed")["payload"] == {"seat_id": master, "stand_in": None}
    seat = run(settings, lambda s: s.get(Seat, master))
    assert seat.occupant_type == "human" and seat.delegated_from is None


def test_combat_turn_of_absent_hero_is_skipped(game_client, admin_g, settings):
    c, (p1,), hero = party(game_client, admin_g, master={"type": "owner"})
    tune(settings, c["id"], reconnect_grace_sec=30, away_skip_sec=0.3)
    _setup(settings, c["id"], hero["id"], "creature.goblin", zone="far", first="hero")
    with connect(game_client, admin_g, c["id"]) as (wm, _):
        with connect(game_client, p1, c["id"]):
            pass
        # ход героя пропущен, за ним ходит гоблин, и очередь снова у героя
        assert next_of(wm, "turn.changed")["payload"]["turn"]["round"] == 2
        with connect(game_client, p1, c["id"]):
            pass  # вернулся: следующие ходы уже не пропускаются сами (и сразу снова ушёл)
    ev = rows(settings, Event, Event.campaign_id == c["id"], Event.tool == "turn_end")
    assert ev[0].payload == {**ev[0].payload, "reason": "away", "action": "пропускает ход: игрок вне сети"}


def test_waiting_for_replies_skips_absent_player(game_client, admin_g, settings, llm):
    c, p1, p2, _ = two_players(game_client, admin_g, settings, collect_window_sec=300)
    tune(settings, c["id"], reconnect_grace_sec=30)
    with connect(game_client, p2, c["id"]) as (w2, snap):
        arag = seat_of(snap, "Арагорн")
        with connect(game_client, p1, c["id"]):
            pass
        presence_until(w2, arag, "reconnecting")
        # окно сбора — 5 минут, но ушедшего не ждём: мастер отвечает сразу
        llm.replies += [DONE, DONE, {"text": "Торин открывает дверь."}]
        w2.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Открываю дверь"}})
        assert narration(w2).endswith("открывает дверь.")
        game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])


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
