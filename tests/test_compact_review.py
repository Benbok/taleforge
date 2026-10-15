"""Bounded review requests and durable retry state without duplicate paid tasks."""
# ruff: noqa: F811 -- shared integration fixtures

import asyncio

import httpx
import pytest

from app.db.models import Event, InventoryItem, LlmCall
from tests.game import FIGHTER, ok, run
from tests.test_api import invite, make_campaign, register
from tests.test_master import admin_g, dice, game_client, llm, rows  # noqa: F401


def submitted(client, admin, monkeypatch):
    campaign = make_campaign(client, admin, players=1)
    cid = campaign["id"]
    ok(client.patch(f"/api/campaigns/{cid}", headers=admin, json={"llm_optimization": {"compact_review": True}}))
    player = register(client, invite(client, admin, cid)["token"], "Reviewer player")
    hero = ok(client.post(f"/api/campaigns/{cid}/characters", json=FIGHTER, headers=player), 201)
    master = client.app.state.master
    schedule = master.schedule_review
    monkeypatch.setattr(master, "schedule_review", lambda *_: None)
    ok(client.post(f"/api/campaigns/{cid}/characters/{hero['id']}/submit", headers=player))
    monkeypatch.setattr(master, "schedule_review", schedule)
    return cid, player, hero, master


def test_review_has_two_responses_and_restores_failure(game_client, admin_g, llm, settings, monkeypatch):
    cid, player, hero, master = submitted(game_client, admin_g, monkeypatch)
    llm.replies += [{"text": "I approve"}, {"text": "Approved again"}]
    game_client.portal.call(master.review_character, cid, hero["id"])
    calls = rows(settings, LlmCall, LlmCall.campaign_id == cid, LlmCall.purpose == "review")
    assert len(calls) == 2
    assert all(c.diagnostics["review_outcome"] == "no_tool_call" for c in calls)
    assert all(r["tool_choice"] == "required" for r in llm.requests if r.get("tools"))
    view = ok(game_client.get(f"/api/campaigns/{cid}/characters/{hero['id']}", headers=player))
    assert view["status"] == "submitted" and view["review_status"] == "failed"
    assert "review_character" in view["review_error"]
    assert view["review_attempt_id"]
    assert not master._reviews


def test_review_repairs_arguments_once_and_executes_one_decision(game_client, admin_g, llm, settings, monkeypatch):
    cid, player, hero, master = submitted(game_client, admin_g, monkeypatch)
    llm.replies += [
        {"tool_calls": [("review_character", {"approve": {"invalid": True}})]},
        {
            "tool_calls": [
                ("review_character", {"approve": True, "comment": "Fits"}),
                ("review_character", {"approve": True, "comment": "Duplicate"}),
            ]
        },
    ]
    assert game_client.portal.call(master.review_character, cid, hero["id"]) == "approved"
    calls = rows(settings, LlmCall, LlmCall.campaign_id == cid, LlmCall.purpose == "review")
    assert len(calls) == 2 and calls[0].diagnostics["review_outcome"] == "invalid_arguments"
    assert calls[1].diagnostics["review_outcome"] == "applied"
    assert len(rows(settings, Event, Event.campaign_id == cid, Event.tool == "review_character")) == 1
    assert rows(settings, InventoryItem, InventoryItem.character_id == hero["id"])


def test_review_started_from_old_process_is_interrupted_without_retry(game_client, admin_g, llm, settings, monkeypatch):
    cid, player, hero, master = submitted(game_client, admin_g, monkeypatch)

    async def old_attempt(s):
        s.add(
            Event(
                campaign_id=cid,
                target_id=hero["id"],
                tool="review_started",
                payload={"attempt_id": "old", "process_id": "old_process"},
            )
        )
        await s.commit()

    run(settings, old_attempt)
    view = ok(game_client.get(f"/api/campaigns/{cid}/characters/{hero['id']}", headers=player))
    assert view["review_status"] == "interrupted" and view["review_error"]
    assert not llm.requests


def test_retry_during_active_session_returns_conflict(game_client, admin_g, llm, settings, monkeypatch):
    from app.db.models import Campaign

    cid, player, hero, master = submitted(game_client, admin_g, monkeypatch)

    async def active(s):
        c = await s.get(Campaign, cid)
        c.status = "active"
        await s.commit()

    run(settings, active)
    response = game_client.post(f"/api/campaigns/{cid}/characters/{hero['id']}/review/retry-ai", headers=player)
    assert response.status_code == 409
    assert not llm.requests


@pytest.mark.parametrize("cancelled", [False, True])
def test_failed_provider_clears_running_attempt(game_client, admin_g, monkeypatch, cancelled):
    from app.agents.llm import LLMError

    cid, player, hero, master = submitted(game_client, admin_g, monkeypatch)

    async def fail(*args, **kwargs):
        if cancelled:
            raise asyncio.CancelledError
        raise LLMError("provider unavailable")

    monkeypatch.setattr(master, "_ask", fail)
    if cancelled:
        # Check cleanup on the application's event loop without cancelling the portal future.
        async def exercise():
            with pytest.raises(asyncio.CancelledError):
                await master.review_character(cid, hero["id"])

        game_client.portal.call(exercise)
    else:
        game_client.portal.call(master.review_character, cid, hero["id"])
    assert not master._reviews
    view = ok(game_client.get(f"/api/campaigns/{cid}/characters/{hero['id']}", headers=player))
    assert view["review_status"] == "failed" and view["review_error"]


@pytest.mark.parametrize("race", ["duplicate", "session", "human"])
def test_running_attempt_coalesces_and_rechecks_admission(game_client, admin_g, settings, monkeypatch, race):
    from app.agents.llm import LLMReply, ToolCall
    from app.db.models import Campaign

    cid, player, hero, master = submitted(game_client, admin_g, monkeypatch)

    async def old_failure(s):
        s.add(Event(campaign_id=cid, target_id=hero["id"], tool="review_failed", payload={"error": "OLD_ERROR"}))
        await s.commit()

    run(settings, old_failure)

    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()
        requests = []

        class Client:
            async def complete(self, messages, **options):
                requests.append(options)
                started.set()
                await release.wait()
                return LLMReply(
                    text="",
                    tool_calls=[ToolCall("call", "review_character", {"approve": True, "comment": "Fits"})],
                    model="m",
                )

        master.llm = Client()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=game_client.app), base_url="http://test") as ac:
            first = await ac.post(f"/api/campaigns/{cid}/characters/{hero['id']}/review/retry-ai", headers=player)
            assert first.status_code == 202, first.text
            await asyncio.wait_for(started.wait(), timeout=3)
            before = (await ac.get(f"/api/campaigns/{cid}/characters/{hero['id']}", headers=player)).json()
            assert before["review_status"] == "running" and before["review_error"] is None
            second = await ac.post(f"/api/campaigns/{cid}/characters/{hero['id']}/review/retry-ai", headers=player)
            assert second.status_code == 202 and first.json()["attempt_id"] == second.json()["attempt_id"]
            if race == "session":
                async with master.maker() as s:
                    c = await s.get(Campaign, cid)
                    c.status = "active"
                    await s.commit()
            elif race == "human":
                response = await ac.post(
                    f"/api/campaigns/{cid}/characters/{hero['id']}/review", json={"approve": True}, headers=admin_g
                )
                assert response.status_code == 200, response.text
            release.set()
            await asyncio.wait_for(master.wait_idle(), timeout=5)
            after = (await ac.get(f"/api/campaigns/{cid}/characters/{hero['id']}", headers=player)).json()
            assert len(requests) == 1 and not master._reviews
            return after

    after = game_client.portal.call(exercise)
    if race == "session":
        assert after["status"] == "submitted" and after["review_status"] == "failed"
        assert not rows(settings, InventoryItem, InventoryItem.character_id == hero["id"])
    else:
        assert after["status"] == "approved"
        assert len(rows(settings, Event, Event.campaign_id == cid, Event.tool == "review_character")) == 1
        inventory = rows(settings, InventoryItem, InventoryItem.character_id == hero["id"])
        assert inventory and len({i.item_template_id for i in inventory}) == len(inventory)
