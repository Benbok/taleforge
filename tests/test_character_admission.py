import asyncio

import httpx
import pytest
from sqlalchemy import select

from app.db.models import Campaign, Character, Event, MasterTurn, Scene
from tests.game import FIGHTER, import_base, ok, party, run
from tests.test_api import invite, make_campaign, register

ADMISSION_MSG = "Новый герой может вступить до старта или на паузе после завершения боя и хода мастера"


@pytest.fixture
def base(settings):
    import_base(settings)


def test_admission_allowed_in_lobby(client, admin, base):
    c = make_campaign(client, admin, players=2, creation_rules={"review": "auto"})
    inv = invite(client, admin, c["id"])
    p1 = register(client, inv["token"], "Арагорн")

    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p1), 201)
    res = ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=p1))
    assert res["status"] == "approved"


def test_admission_allowed_on_calm_pause(client, admin, base):
    c, (p1, p2), _ = party(client, admin, players=2)
    client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin)
    c_info = client.get(f"/api/campaigns/{c['id']}", headers=admin).json()
    assert c_info["status"] == "paused"

    ch2 = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p2), 201)
    res = ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch2['id']}/submit", headers=p2))
    assert res["status"] == "approved"


def test_admission_forbidden_during_active_session(client, admin, base):
    c, (p1, p2), _ = party(client, admin, players=2, master={"type": "owner"})
    # Session is active (party starts session)
    # Owner expands seat to invite new player
    ok(client.post(f"/api/campaigns/{c['id']}/seats", headers=admin), 201)
    inv = invite(client, admin, c["id"])
    p_new = register(client, inv["token"], "Боромир")

    # 1. Draft submit forbidden
    ch2 = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p_new), 201)
    r_submit = client.post(f"/api/campaigns/{c['id']}/characters/{ch2['id']}/submit", headers=p_new)
    assert r_submit.status_code == 409
    assert ADMISSION_MSG in r_submit.json()["detail"]
    ch2_curr = client.get(f"/api/campaigns/{c['id']}/characters/{ch2['id']}", headers=p_new).json()
    assert ch2_curr["status"] == "draft"

    # 2. Premade claim forbidden
    pre = ok(client.post(f"/api/campaigns/{c['id']}/premades", json=FIGHTER, headers=admin), 201)
    r_claim = client.post(f"/api/campaigns/{c['id']}/characters/{pre['id']}/claim", headers=p_new)
    assert r_claim.status_code == 409
    assert ADMISSION_MSG in r_claim.json()["detail"]

    # 3. Human review forbidden
    # Put ch2 in submitted directly via DB to test review endpoint
    async def force_submitted(s):
        char = await s.get(Character, ch2["id"])
        char.status = "submitted"
        await s.commit()

    run(client.app.state.settings, force_submitted)
    r_review = client.post(
        f"/api/campaigns/{c['id']}/characters/{ch2['id']}/review",
        json={"approve": True, "comment": ""},
        headers=admin,
    )
    assert r_review.status_code == 409
    assert ADMISSION_MSG in r_review.json()["detail"]


def test_original_reserved_seat_cannot_submit_during_active_session(client, admin, base):
    c, (p1, p2), _ = party(client, admin, players=2, master={"type": "owner"})
    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p2), 201)

    response = client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=p2)
    assert response.status_code == 409
    assert ADMISSION_MSG in response.json()["detail"]


def test_claim_atomicity_on_rejection(client, admin, base):
    c, _, _ = party(client, admin, players=2)
    # Session active

    ok(client.post(f"/api/campaigns/{c['id']}/seats", headers=admin), 201)
    inv = invite(client, admin, c["id"])
    p_new = register(client, inv["token"], "Боромир")

    # The late-joining player creates their own draft.
    draft = ok(
        client.post(f"/api/campaigns/{c['id']}/characters", json={"name": "Черновик Гимли"}, headers=p_new),
        201,
    )
    pre = ok(client.post(f"/api/campaigns/{c['id']}/premades", json=FIGHTER, headers=admin), 201)

    r = client.post(f"/api/campaigns/{c['id']}/characters/{pre['id']}/claim", headers=p_new)
    assert r.status_code == 409

    # Verify draft was NOT deleted
    draft_check = client.get(f"/api/campaigns/{c['id']}/characters/{draft['id']}", headers=p_new).json()
    assert draft_check["id"] == draft["id"]
    assert draft_check["status"] == "draft"
    assert draft_check["name"] == "Черновик Гимли"

    # Verify premade was NOT claimed
    pre_check = client.get(f"/api/campaigns/{c['id']}/characters/{pre['id']}", headers=admin).json()
    assert pre_check["status"] == "premade"
    assert pre_check["seat_id"] is None


def test_admission_forbidden_on_paused_with_combat(client, admin, base):
    c, _, _ = party(client, admin, players=2)
    ok(client.post(f"/api/campaigns/{c['id']}/seats", headers=admin), 201)
    inv = invite(client, admin, c["id"])
    p_new = register(client, inv["token"], "Боромир")

    # Set scene mode to combat
    async def enter_combat(s):
        sc = await s.get(Scene, c["id"])
        sc.mode = "combat"
        sc.turn_order = [{"id": "x", "initiative": 10}]
        await s.commit()

    run(client.app.state.settings, enter_combat)

    # Pause session
    client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin)
    c_info = client.get(f"/api/campaigns/{c['id']}", headers=admin).json()
    assert c_info["status"] == "paused"

    ch2 = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p_new), 201)

    r_submit = client.post(f"/api/campaigns/{c['id']}/characters/{ch2['id']}/submit", headers=p_new)
    assert r_submit.status_code == 409
    assert ADMISSION_MSG in r_submit.json()["detail"]


def test_admission_forbidden_in_ended_campaign(client, admin, base):
    c, (p1, p2), _ = party(client, admin, players=2)
    client.post(f"/api/campaigns/{c['id']}/session/end", headers=admin)

    ch2 = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p2), 201)

    r_submit = client.post(f"/api/campaigns/{c['id']}/characters/{ch2['id']}/submit", headers=p2)
    assert r_submit.status_code == 409
    assert ADMISSION_MSG in r_submit.json()["detail"]


def test_pending_turn_blocks_admission(client, admin, base):
    c, _, _ = party(client, admin, players=2)
    ok(client.post(f"/api/campaigns/{c['id']}/seats", headers=admin), 201)
    inv = invite(client, admin, c["id"])
    p_new = register(client, inv["token"], "Боромир")
    client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin)

    # Insert a running master turn
    async def add_running_turn(s):
        s.add(MasterTurn(campaign_id=c["id"], status="running"))
        await s.commit()

    run(client.app.state.settings, add_running_turn)

    ch2 = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p_new), 201)

    r_submit = client.post(f"/api/campaigns/{c['id']}/characters/{ch2['id']}/submit", headers=p_new)
    assert r_submit.status_code == 409
    assert ADMISSION_MSG in r_submit.json()["detail"]


def test_paused_secondary_combat_front_blocks_admission(client, admin, base):
    c, _, _ = party(client, admin, players=2)
    ok(client.post(f"/api/campaigns/{c['id']}/seats", headers=admin), 201)
    inv = invite(client, admin, c["id"])
    p_new = register(client, inv["token"], "Боромир")

    # Secondary combat front: scene.mode may be free, but turn_order still has combatants
    async def set_secondary_front(s):
        sc = await s.get(Scene, c["id"])
        sc.mode = "free"
        sc.turn_order = [{"id": "goblin_1", "initiative": 12}]
        await s.commit()

    run(client.app.state.settings, set_secondary_front)
    client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin)

    ch2 = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p_new), 201)

    r_submit = client.post(f"/api/campaigns/{c['id']}/characters/{ch2['id']}/submit", headers=p_new)
    assert r_submit.status_code == 409
    assert ADMISSION_MSG in r_submit.json()["detail"]


def test_start_races_with_admission(client, admin, base):
    c = make_campaign(client, admin, players=2, creation_rules={"review": "auto"})
    inv = invite(client, admin, c["id"])
    p1 = register(client, inv["token"], "Арагорн")
    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p1), 201)

    async def race():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        ) as ac:
            return await asyncio.gather(
                ac.post(f"/api/campaigns/{c['id']}/session/start", headers=admin),
                ac.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=p1),
            )

    r_start, r_submit = client.portal.call(race)
    # Both shouldn't succeed with inconsistent state:
    # If start finished first: submit got 409. If submit finished first: both 200.
    if r_submit.status_code == 409:
        assert ADMISSION_MSG in r_submit.json()["detail"]
        ch_curr = client.get(f"/api/campaigns/{c['id']}/characters/{ch['id']}", headers=p1).json()
        assert ch_curr["status"] == "draft"
    else:
        assert r_submit.status_code == 200
        assert r_submit.json()["status"] == "approved"


def test_ai_review_finishes_after_resume(client, admin, base, monkeypatch):
    # This test drives review directly; keep submission from starting a competing task.
    monkeypatch.setattr(client.app.state.master, "schedule_review", lambda *_: None)
    c = make_campaign(
        client,
        admin,
        players=1,
        creation_rules={"review": "master"},
        master={"type": "agent", "provider": "claude", "model": "x"},
    )
    inv = invite(client, admin, c["id"])
    register(client, inv["token"], "Арагорн")
    ok(client.post(f"/api/campaigns/{c['id']}/seats", headers=admin), 201)
    late_inv = invite(client, admin, c["id"])
    p_new = register(client, late_inv["token"], "Боромир")
    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p_new), 201)
    sub = ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=p_new))
    assert sub["status"] == "submitted"

    master = client.app.state.master

    # Simulate model call during which session resumes
    async def ask_and_resume(*args, **kwargs):
        # Session resumes while AI is thinking
        async with client.app.state.sessionmaker() as s:
            cmp = await s.get(Campaign, c["id"])
            cmp.status = "active"
            await s.commit()
        from unittest.mock import MagicMock
        reply = MagicMock()
        reply.message = None
        reply.text = "Одобряю"
        call = MagicMock()
        call.name = "review_character"
        call.id = "c1"
        call.arguments = {"character_id": ch["id"], "approve": True, "comment": "Отличный герой"}
        reply.tool_calls = [call]
        return reply

    monkeypatch.setattr(master, "_ask", ask_and_resume)

    # Run review
    res = client.portal.call(master.review_character, c["id"], ch["id"])
    assert res is None

    # A compact review records the admission race and leaves the character submitted.
    async def check_events(s):
        evs = (await s.scalars(select(Event).where(Event.campaign_id == c["id"], Event.tool == "review_failed"))).all()
        return len(evs)

    assert run(client.app.state.settings, check_events) == 1

    # Character is still submitted
    ch_state = client.get(f"/api/campaigns/{c['id']}/characters/{ch['id']}", headers=p_new).json()
    assert ch_state["status"] == "submitted"

    # Now pause session, restore normal review, retry AI review
    async def set_paused(s):
        cmp = await s.get(Campaign, c["id"])
        cmp.status = "paused"
        await s.commit()

    run(client.app.state.settings, set_paused)

    async def ask_normal(*args, **kwargs):
        from unittest.mock import MagicMock
        reply = MagicMock()
        reply.message = None
        reply.text = "Одобряю"
        call = MagicMock()
        call.name = "review_character"
        call.id = "c1"
        call.arguments = {"character_id": ch["id"], "approve": True, "comment": "Отличный герой"}
        reply.tool_calls = [call]
        return reply

    monkeypatch.setattr(master, "_ask", ask_normal)
    retry_res = client.portal.call(master.review_character, c["id"], ch["id"])
    assert retry_res == "approved"
    ch_final = client.get(f"/api/campaigns/{c['id']}/characters/{ch['id']}", headers=p_new).json()
    assert ch_final["status"] == "approved"


def test_session_start_does_not_wait_for_ai_character_review(client, admin, base, monkeypatch):
    c = make_campaign(
        client,
        admin,
        players=1,
        creation_rules={"review": "master"},
        master={"type": "agent", "provider": "claude", "model": "x"},
    )
    inv = invite(client, admin, c["id"])
    player = register(client, inv["token"], "Арагорн")
    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=player), 201)

    async def force_submitted(s):
        character = await s.get(Character, ch["id"])
        character.status = "submitted"
        await s.commit()

    run(client.app.state.settings, force_submitted)
    master = client.app.state.master
    model_started = asyncio.Event()
    release_model = asyncio.Event()

    async def slow_ask(*args, **kwargs):
        model_started.set()
        await release_model.wait()
        raise asyncio.CancelledError

    monkeypatch.setattr(master, "_ask", slow_ask)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://testserver"
        ) as ac:
            review_task = asyncio.create_task(master.review_character(c["id"], ch["id"]))
            await asyncio.wait_for(model_started.wait(), timeout=1)
            start_task = asyncio.create_task(ac.post(f"/api/campaigns/{c['id']}/session/start", headers=admin))
            done, _ = await asyncio.wait({start_task}, timeout=1)
            completed_while_model_waited = start_task in done
            release_model.set()
            try:
                await review_task
            except asyncio.CancelledError:
                pass
            response = await start_task
            return completed_while_model_waited, response

    completed_while_model_waited, response = client.portal.call(exercise)
    assert completed_while_model_waited
    assert response.status_code == 200, response.text
