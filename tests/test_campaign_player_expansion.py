from __future__ import annotations

import asyncio
import httpx
import pytest
from sqlalchemy import select

from app.db.models import Character, Seat
from tests.conftest import login
from tests.test_api import invite, make_campaign, register


def test_owner_adds_third_seat(client, admin):
    c = make_campaign(client, admin, players=2)
    assert len(c["seats"]) == 3
    old_seats = {s["position"]: s for s in c["seats"]}
    old_settings = dict(c["settings"])

    r = client.post(f"/api/campaigns/{c['id']}/seats", headers=admin)
    assert r.status_code == 201, r.text
    expanded = r.json()

    assert len(expanded["seats"]) == 4
    # Old seats preserved
    for pos, old in old_seats.items():
        current = next(s for s in expanded["seats"] if s["position"] == pos)
        assert current["id"] == old["id"]
        assert current["role"] == old["role"]
        assert current["occupant_type"] == old["occupant_type"]

    # Master seat intact
    master_seat = next(s for s in expanded["seats"] if s["role"] == "master")
    assert master_seat["id"] == old_seats[0]["id"]
    assert master_seat["position"] == 0

    # New seat properties
    new_seat = next(s for s in expanded["seats"] if s["position"] == 3)
    assert new_seat["role"] == "player"
    assert new_seat["occupant_type"] == "empty"
    assert new_seat["user_id"] is None
    assert new_seat.get("agent_provider") is None

    # Settings unchanged
    assert expanded["settings"] == old_settings

    # No character was created
    chars = client.get(f"/api/campaigns/{c['id']}/characters", headers=admin).json()
    assert len(chars) == 0


def test_non_owner_cannot_expand(client, admin):
    c = make_campaign(client, admin, players=2)
    inv = invite(client, admin, c["id"])
    player_headers = register(client, inv["token"], "Боромир")

    # Player cannot expand
    r = client.post(f"/api/campaigns/{c['id']}/seats", headers=player_headers)
    assert r.status_code == 403

    # Unauthenticated user cannot expand
    r2 = client.post(f"/api/campaigns/{c['id']}/seats")
    assert r2.status_code == 401


def test_ended_campaign_cannot_expand(client, admin):
    c = make_campaign(client, admin, players=2)
    # Start and end campaign session
    client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin)
    client.post(f"/api/campaigns/{c['id']}/session/end", headers=admin)
    c_ended = client.get(f"/api/campaigns/{c['id']}", headers=admin).json()
    assert c_ended["status"] == "ended"

    r = client.post(f"/api/campaigns/{c['id']}/seats", headers=admin)
    assert r.status_code == 409
    assert "завершена" in r.json()["detail"].lower()


def test_six_seats_is_limit(client, admin):
    c = make_campaign(client, admin, players=6)
    assert len(c["seats"]) == 7  # 1 master + 6 players

    r = client.post(f"/api/campaigns/{c['id']}/seats", headers=admin)
    assert r.status_code == 409
    assert "предел" in r.json()["detail"].lower() or "6" in r.json()["detail"]


def test_expansion_allowed_during_session(client, admin):
    c = make_campaign(client, admin, players=2)
    client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin)
    active = client.get(f"/api/campaigns/{c['id']}", headers=admin).json()
    assert active["status"] == "active"

    r = client.post(f"/api/campaigns/{c['id']}/seats", headers=admin)
    assert r.status_code == 201
    assert len(r.json()["seats"]) == 4


def test_existing_invite_uses_added_seat(client, admin):
    c = make_campaign(client, admin, players=2)
    inv = invite(client, admin, c["id"], max_uses=3)

    # 2 players join, filling both player seats
    p1 = register(client, inv["token"], "Арагорн")
    p2 = register(client, inv["token"], "Гимли")

    prev = client.get(f"/api/invites/{inv['token']}").json()
    assert prev["free_seats"] == 0
    assert not prev["valid"]

    # Owner adds a seat
    r = client.post(f"/api/campaigns/{c['id']}/seats", headers=admin)
    assert r.status_code == 201

    # Preview now shows 1 free seat and valid invite
    prev2 = client.get(f"/api/invites/{inv['token']}").json()
    assert prev2["free_seats"] == 1
    assert prev2["valid"]

    # Third player joins
    p3 = register(client, inv["token"], "Леголас")
    c_after = client.get(f"/api/campaigns/{c['id']}", headers=p3).json()
    seat3 = next(s for s in c_after["seats"] if s["position"] == 3)
    assert seat3["user_name"] == "Леголас"
    assert seat3["occupant_type"] == "human"


def test_repeat_join_does_not_consume_another_seat(client, admin):
    c = make_campaign(client, admin, players=2)
    inv = invite(client, admin, c["id"], max_uses=5)

    p1 = register(client, inv["token"], "Арагорн")

    # Owner adds a 3rd seat
    client.post(f"/api/campaigns/{c['id']}/seats", headers=admin)

    # p1 accepts invite again
    r = client.post(f"/api/invites/{inv['token']}/accept", headers=p1)
    assert r.status_code == 200
    c_curr = r.json()

    # Free seats count should still be 2 (positions 2 and 3)
    empty = [s for s in c_curr["seats"] if s["role"] == "player" and s["occupant_type"] == "empty"]
    assert len(empty) == 2


def test_concurrent_expansion_at_limit(client, admin):
    c = make_campaign(client, admin, players=5)

    async def concurrent_expand():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        ) as ac:
            return await asyncio.gather(
                ac.post(f"/api/campaigns/{c['id']}/seats", headers=admin),
                ac.post(f"/api/campaigns/{c['id']}/seats", headers=admin),
            )

    r1, r2 = client.portal.call(concurrent_expand)
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [201, 409], f"Got statuses: {statuses}"

    final_c = client.get(f"/api/campaigns/{c['id']}", headers=admin).json()
    player_seats = [s for s in final_c["seats"] if s["role"] == "player"]
    assert len(player_seats) == 6


def test_concurrent_expansion_preserves_unique_positions(client, admin):
    c = make_campaign(client, admin, players=4)

    async def concurrent_expand():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        ) as ac:
            return await asyncio.gather(
                ac.post(f"/api/campaigns/{c['id']}/seats", headers=admin),
                ac.post(f"/api/campaigns/{c['id']}/seats", headers=admin),
            )

    r1, r2 = client.portal.call(concurrent_expand)
    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text

    final_c = client.get(f"/api/campaigns/{c['id']}", headers=admin).json()
    player_seats = [s for s in final_c["seats"] if s["role"] == "player"]
    assert len(player_seats) == 6
    positions = [s["position"] for s in player_seats]
    assert sorted(positions) == [1, 2, 3, 4, 5, 6]
    assert len(set(positions)) == 6
