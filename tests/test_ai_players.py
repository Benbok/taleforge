# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""ИИ-игроки (этап 9а, ТЗ раздел 5.2): место и герой, подсказка ролей, реплика после мастера, ход в бою, реакция,
«передать ИИ» в голосовании офлайна, живой игрок занимает место ИИ."""

from types import SimpleNamespace

from app.db.models import Message, Seat
from tests.game import FIGHTER, ok, party, run
from tests.test_master import DONE, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры


def empty_seat(client, admin, cid):
    c = ok(client.get(f"/api/campaigns/{cid}", headers=admin))
    return next(s["id"] for s in c["seats"] if s["role"] == "player" and s["occupant_type"] == "empty")


def ai_party(client, admin, *, expanded=False, **kw):
    """Живой игрок с воином и ИИ-игрок с героем, которого собрал владелец."""
    if expanded:
        c, (p1,), hero = party(client, admin, players=1, **kw)
        ok(client.post(f"/api/campaigns/{c['id']}/seats", headers=admin), 201)
        return c, p1, hero
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
    camp = client.get(f"/api/campaigns/{cid}", headers=admin).json()
    was_active = camp["status"] == "active"
    if was_active:
        ok(client.post(f"/api/campaigns/{cid}/session/pause", headers=admin))
    res = ok(client.post(f"/api/campaigns/{cid}/characters/{ch['id']}/submit{q}", headers=admin))
    assert res["status"] == "approved", res
    if was_active:
        ok(client.post(f"/api/campaigns/{cid}/session/start", headers=admin))
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


def test_ai_player_reaction_follows_mood(game_client):
    master = game_client.app.state.master
    ai = Seat(id="s1", role="player", occupant_type="agent")
    careful = Seat(id="s2", role="player", occupant_type="agent", delegated_from="u1")
    ctx = SimpleNamespace(campaign=SimpleNamespace(id="c", seats=[ai, careful], settings={}))
    hit = game_client.portal.call(master._ask_reaction, ctx, SimpleNamespace(id="h", seat_id="s1"), None)
    skip = game_client.portal.call(master._ask_reaction, ctx, SimpleNamespace(id="h", seat_id="s2"), None)
    assert hit is True and skip is False
