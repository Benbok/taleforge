# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""ИИ-игроки (этап 9а, ТЗ раздел 5.2): место и герой, подсказка ролей, реплика после мастера, ход в бою, реакция,
«передать ИИ» в голосовании офлайна, живой игрок занимает место ИИ."""

from types import SimpleNamespace

from app.db.models import Character, LlmCall, Message, Seat
from tests.game import FIGHTER, ok, party, run
from tests.test_api import invite, register
from tests.test_combat import _setup
from tests.test_master import DONE, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_offline import narration, presence_until, seat_of, tune
from tests.test_ws import connect, next_of


def empty_seat(client, admin, cid):
    c = ok(client.get(f"/api/campaigns/{cid}", headers=admin))
    return next(s["id"] for s in c["seats"] if s["role"] == "player" and s["occupant_type"] == "empty")


def ai_party(client, admin, **kw):
    """Живой игрок с воином и ИИ-игрок с героем, которого собрал владелец."""
    c, (p1, p2), hero = party(client, admin, players=2, **kw)
    snap = ok(client.get(f"/api/campaigns/{c['id']}", headers=admin))
    gimli = next(s["id"] for s in snap["seats"] if s["user_name"] == "Гимли")
    ok(client.delete(f"/api/campaigns/{c['id']}/seats/{gimli}/occupant", headers=admin))
    return c, p1, hero


def seat_ai(client, admin, cid):
    seat = empty_seat(client, admin, cid)
    out = ok(client.post(f"/api/campaigns/{cid}/seats/{seat}/agent", json={}, headers=admin))
    assert next(s for s in out["seats"] if s["id"] == seat)["occupant_type"] == "agent"
    return seat


def build_hero(client, admin, cid, seat, body=None):
    body = body or {**FIGHTER, "name": "Торин", "private_backstory": "Потерял брата в шахтах."}
    q = f"?as_seat={seat}"
    ch = ok(client.post(f"/api/campaigns/{cid}/characters{q}", json=body, headers=admin), 201)
    res = ok(client.post(f"/api/campaigns/{cid}/characters/{ch['id']}/submit{q}", headers=admin))
    assert res["status"] == "approved", res
    return ch


def whisper(settings, cid, seat_id):
    """Мастер шепчет живому игроку: такой шёпот ИИ-игрок не видит."""
    from app.core.campaigns import master_seat
    from app.core.chat import next_seq
    from app.db.models import Campaign

    async def go(s):
        c = await s.get(Campaign, cid)
        s.add(
            Message(
                campaign_id=cid,
                seq=await next_seq(s, cid),
                seat_id=master_seat(c).id,
                kind="whisper",
                visible_to=[seat_id],
                content="тайный план",
            )
        )
        await s.commit()

    run(settings, go)


def test_owner_seats_ai_and_builds_its_hero(game_client, admin_g, settings):
    c, p1, _ = ai_party(game_client, admin_g)
    cid = c["id"]
    seat = empty_seat(game_client, admin_g, cid)
    # сажает только владелец и только на пустое место
    r = game_client.post(f"/api/campaigns/{cid}/seats/{seat}/agent", json={}, headers=p1)
    assert r.status_code == 403
    seat_ai(game_client, admin_g, cid)
    r = game_client.post(f"/api/campaigns/{cid}/seats/{seat}/agent", json={}, headers=admin_g)
    assert r.status_code == 409 and "занято" in r.json()["detail"]

    # подсказка ролей: у воина защита и урон, лечения нет — его закроет жрец
    roles = ok(game_client.get(f"/api/campaigns/{cid}/party-roles", headers=admin_g))
    assert {h["role"] for h in roles["have"]} == {"tank", "damage"}
    heal = next(m for m in roles["missing"] if m["role"] == "heal")
    assert "class.cleric" in [x["id"] for x in heal["classes"]]

    # героя ИИ собирает владелец за его место; игрок за ИИ этого не может
    r = game_client.post(f"/api/campaigns/{cid}/characters?as_seat={seat}", json=FIGHTER, headers=p1)
    assert r.status_code == 404
    ch = build_hero(game_client, admin_g, cid, seat)
    hero = run(settings, lambda s: s.get(Character, ch["id"]))
    assert hero.seat_id == seat
    roles = ok(game_client.get(f"/api/campaigns/{cid}/party-roles", headers=admin_g))
    assert roles["heroes"] == 2

    # говорить за ИИ-игрока в чате владелец не может: за него пишет только ИИ
    with connect(game_client, admin_g, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "иду", "as_seat": seat}})
        assert "не ведёте" in next_of(ws, "message.rejected")["payload"]["reason"]


def test_ai_player_answers_once_after_master(game_client, admin_g, settings, llm):
    c, p1, hero = ai_party(game_client, admin_g)
    cid = c["id"]
    seat = seat_ai(game_client, admin_g, cid)
    build_hero(game_client, admin_g, cid, seat)
    with connect(game_client, p1, cid) as (ws, snap):
        me = snap["payload"]["me"]["seat_id"]
        ai = next(s for s in snap["payload"]["seats"] if s["id"] == seat)
        assert ai["occupant_type"] == "agent" and ai["stand_in"] is None
        whisper(settings, cid, me)
        llm.replies += [
            {"text": "«Я пойду первым», — говорит Торин и зажигает факел."},
            DONE,
            DONE,
            {"text": "Факел выхватывает из тьмы ступени."},
        ]
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Бран осматривается"}})
        for _ in range(40):
            m = next_of(ws, "message.new")["payload"]
            if m["seat_id"] == seat:
                break
        assert m["content"].startswith("Я пойду первым") and m["data"] == {"ai": True} and m["author"] is None
        # мастер отвечает на действия всей партии одним повествованием
        assert narration(ws).endswith("ступени.")
        game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    assert llm.replies == []
    calls = rows(settings, LlmCall, LlmCall.campaign_id == cid, LlmCall.purpose == "player")
    assert len(calls) == 1 and calls[0].seat_id == seat
    ask = next(r for r in llm.requests if r["messages"][0]["content"].startswith("Ты — игрок"))
    text = ask["messages"][1]["content"]
    assert "Потерял брата" in text and "Торин" in text  # свой лист и предыстория
    assert "тайный план" not in text and "Бежал из гарнизона" not in text  # чужие шёпоты и тайны — нет


def test_ai_player_takes_its_combat_turn_or_passes(game_client, admin_g, settings, llm):
    c, p1, _ = ai_party(game_client, admin_g, master={"type": "owner"})
    cid = c["id"]
    seat = seat_ai(game_client, admin_g, cid)
    ch = build_hero(game_client, admin_g, cid, seat)
    _setup(settings, cid, ch["id"], "creature.goblin", zone="far")
    llm.replies.append({"text": "Торин бьёт гоблина топором."})
    with connect(game_client, admin_g, cid) as (ws, _):
        ws.send_json({"type": "turn.pass", "payload": {}})  # мастер закрыл ход существа: ход ИИ-героя
        assert next_of(ws, "turn.changed")["payload"]["turn"]["actor_id"] == ch["id"]
        for _ in range(40):
            m = next_of(ws, "message.new")["payload"]
            if m["seat_id"] == seat:
                break
        assert m["kind"] == "action" and m["content"] == "Торин бьёт гоблина топором." and m["data"]["ai"]
        # мастер закрыл и этот ход; снова очередь ИИ — модель промолчала, ход пропущен
        ws.send_json({"type": "turn.pass", "payload": {}})
        next_of(ws, "turn.changed")
        llm.replies.append({"text": "—"})
        ws.send_json({"type": "turn.pass", "payload": {}})
        for _ in range(40):
            m = next_of(ws, "message.new")["payload"]
            if "пропускает ход" in m["content"]:
                break
        assert "Торин" in m["content"]
        game_client.portal.call(game_client.app.state.master.wait_idle, cid)


def test_ai_player_reaction_follows_mood(game_client):
    master = game_client.app.state.master
    ai = Seat(id="s1", role="player", occupant_type="agent")
    careful = Seat(id="s2", role="player", occupant_type="agent", delegated_from="u1")
    ctx = SimpleNamespace(campaign=SimpleNamespace(id="c", seats=[ai, careful], settings={}))
    hit = game_client.portal.call(master._ask_reaction, ctx, SimpleNamespace(id="h", seat_id="s1"), None)
    skip = game_client.portal.call(master._ask_reaction, ctx, SimpleNamespace(id="h", seat_id="s2"), None)
    assert hit is True and skip is False


def test_vote_hands_hero_to_ai_and_back(game_client, admin_g, settings, llm):
    c, (p1, p2), _ = party(game_client, admin_g, players=2)
    ok(game_client.post(f"/api/campaigns/{c['id']}/characters", json={**FIGHTER, "name": "Торин"}, headers=p2), 201)
    tid = rows(settings, Character, Character.name == "Торин")[0].id
    ok(game_client.post(f"/api/campaigns/{c['id']}/characters/{tid}/submit", headers=p2))
    tune(settings, c["id"])
    with connect(game_client, p2, c["id"]) as (w2, snap):
        arag = seat_of(snap, "Арагорн")
        with connect(game_client, p1, c["id"]):
            pass
        presence_until(w2, arag, "offline")
        vote = next_of(w2, "vote.started")["payload"]
        assert "ai_player" in [o["id"] for o in vote["options"]]
        w2.send_json({"type": "vote.cast", "payload": {"vote_id": vote["vote_id"], "option": "ai_player"}})
        assert next_of(w2, "vote.ended")["payload"]["outcome"] == "ai_player"
        assert next_of(w2, "stand_in.changed")["payload"] == {"seat_id": arag, "stand_in": {"ai": True, "name": "ИИ"}}
        seat = run(settings, lambda s: s.get(Seat, arag))
        assert seat.occupant_type == "agent" and seat.delegated_from and seat.agent_config_id

        # ИИ ведёт Брана осторожно: в подсказке модели пометка
        llm.replies += [{"text": "Бран держится позади отряда."}, DONE, DONE, {"text": "Коридор пуст."}]
        w2.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Торин идёт вперёд"}})
        for _ in range(40):
            m = next_of(w2, "message.new")["payload"]
            if m["seat_id"] == arag:
                break
        assert m["content"] == "Бран держится позади отряда."
        assert narration(w2).endswith("Коридор пуст.")
        ask = next(r for r in llm.requests if r["messages"][0]["content"].startswith("Ты — игрок"))
        assert "осторожно" in ask["messages"][0]["content"]
        game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])

        # Арагорн вернулся: место снова его
        llm.replies.append({"text": "Бран держался позади."})
        with connect(game_client, p1, c["id"]) as (_, back):
            assert back["payload"]["me"]["seat_id"] == arag
            assert next_of(w2, "stand_in.changed")["payload"] == {"seat_id": arag, "stand_in": None}
            game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    seat = run(settings, lambda s: s.get(Seat, arag))
    assert seat.occupant_type == "human" and seat.delegated_from is None


def test_player_takes_ai_seat_and_its_hero(game_client, admin_g, settings):
    c, p1, _ = ai_party(game_client, admin_g)
    cid = c["id"]
    seat = seat_ai(game_client, admin_g, cid)
    ch = build_hero(game_client, admin_g, cid, seat)
    ok(game_client.delete(f"/api/campaigns/{cid}/seats/{seat}/occupant", headers=admin_g))
    head = register(game_client, invite(game_client, admin_g, cid)["token"], "Леголас")
    hero = ok(game_client.get(f"/api/campaigns/{cid}/characters/{ch['id']}", headers=head))
    assert hero["name"] == "Торин" and hero["private_backstory"] == "Потерял брата в шахтах."
    got = run(settings, lambda s: s.get(Character, ch["id"]))
    me = ok(game_client.get("/api/auth/me", headers=head))
    assert got.owner_user_id == me["id"] and got.seat_id == seat
    msgs = rows(settings, Message, Message.campaign_id == cid, Message.seat_id == seat)
    assert msgs == []
