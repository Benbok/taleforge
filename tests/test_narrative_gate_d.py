# ruff: noqa: F811 — shared create_app fixtures
"""Gate D: player alliance -> durable future job -> director -> scene -> restart/reconnect."""

import inspect
import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.llm import LLMReply, ScriptedLLM, ToolCall
from app.db.models import CampaignSecret, Character, Event
from app.main import create_app
from tests.game import QueueDice, run
from tests.test_master import act
from tests.test_narrative_master import DONE, admin_g, dice, game_client, llm  # noqa: F401
from tests.test_narrative_startup import (
    NEW_TITLE,
    _director_calls,
    _director_reply,
    _node_title,
    _route_director,
    _settle,
    _setup,
    _works,
)
from tests.test_ws import connect


def test_alliance_future_job_next_scene_and_reconnect(game_client, admin_g, llm, dice, settings):
    cid, player = _setup(game_client, admin_g, settings)

    async def prepare_sketches(s):
        import copy

        secret = await s.get(CampaignSecret, cid)
        plan = copy.deepcopy(secret.plot)
        for kind in ("locations", "npcs"):
            for sketch in plan.get(kind, []):
                sketch.setdefault("status", "sketch")
        secret.plot = plan
        await s.commit()

    run(settings, prepare_sketches)

    def finish_jobs():
        deadline = time.monotonic() + 20
        while True:
            game_client.portal.call(game_client.app.state.master.recover)
            works = _works(settings, cid)
            if works and all(w.status in ("applied", "no_change") and w.lease_token is None for w in works):
                return
            assert time.monotonic() < deadline, [(w.status, w.draft) for w in works]
            time.sleep(0.05)

    async def hero_id(s):
        return await s.scalar(select(Character.id).where(Character.campaign_id == cid))

    hid = run(settings, hero_id)
    dice[:] = [20, 20]
    director_count = 0
    narration_text = "Союз заключён. Герои готовятся защищать склеп."
    complete = llm.complete

    async def scene_and_narration(messages, **kwargs):
        user_text = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
        intro = "Продолжай уже рассказанное в фактическом месте" in user_text
        narration = "Фаза повествования. Изменять мир больше нельзя" in user_text
        if kwargs.get("tools") is None and (intro or narration):
            text = "Место перед вами." if intro else narration_text
            llm.requests.append({"messages": messages, "tools": None})
            if callback := kwargs.get("stream_callback"):
                sent = callback(text)
                if inspect.isawaitable(sent):
                    await sent
            return LLMReply(text=text, model="m", tokens_in=100, tokens_out=10)
        return await complete(messages, **kwargs)

    llm.complete = scene_and_narration

    def director(messages, tools):
        nonlocal director_count
        director_count += 1
        if director_count == 1:
            return _director_reply(messages, tools)
        return LLMReply(
            text="",
            tool_calls=[
                ToolCall(
                    "no-change",
                    "propose_adaptation",
                    {
                        "summary": "Союз сохраняется",
                        "operations": [],
                    },
                    "",
                )
            ],
            model="m",
            tokens_in=100,
            tokens_out=10,
        )

    asked = _route_director(llm, director)
    llm.replies += [
        {
            "tool_calls": [
                (
                    "roll_check",
                    {
                        "character_id": hid,
                        "stat": "persuasion",
                        "difficulty": "dc.medium",
                        "reason": "договориться с хранителем о союзе",
                    },
                )
            ]
        },
        {
            "tool_calls": [
                (
                    "adapt_story",
                    {
                        "slot_ref": 0,
                        "grounds": [
                            {"kind": "relationship", "evidence_refs": [{"kind": "message", "source_id": "current"}]}
                        ],
                        "summary": "Хранитель заключает союз с героями",
                        "operations": [
                            {
                                "kind": "change_front_intent",
                                "front_ref": {
                                    "campaign_id": cid,
                                    "source_kind": "antagonist",
                                    "source_id": "villain",
                                },
                                "new_intent": "Защищать склеп вместе с героями",
                                "status": "stopped",
                            }
                        ],
                    },
                )
            ]
        },
        {"tool_calls": [("end_act", {"outcome": "Герои заключили союз с хранителем вместо боя"})]},
        DONE,
        DONE,
    ]
    act(game_client, player, cid, "Предлагаю хранителю союз: вместе защитим склеп")
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    finish_jobs()
    first_work = _works(settings, cid)[0]
    assert first_work.scope == "future" and first_work.status == "applied"
    assert first_work.evidence_refs and first_work.receipt_event_id
    assert _node_title(settings, cid) == NEW_TITLE

    async def verify_alliance(s):
        plan = (await s.get(CampaignSecret, cid)).plot
        assert plan["antagonists"][0]["goal"] == "Защищать склеп вместе с героями"
        assert plan["antagonists"][0]["stopped"] is True
        assert plan["acts"][0]["outcome"] == "Герои заключили союз с хранителем вместо боя"
        receipt = await s.get(Event, first_work.receipt_event_id)
        assert receipt.payload["source"]["source_kind"] == "work"
        for ref in first_work.evidence_refs:
            assert await s.get(Event, ref["source_id"]) is not None

    run(settings, verify_alliance)
    llm.replies.clear()
    narration_text = "Герои входят в склеп."
    llm.replies += [
        {"tool_calls": [("end_act", {"outcome": "Союзники добрались до склепа"})]},
        {
            "tool_calls": [
                ("develop", {"sketch_id": "loc_crypt", "details": "Место переговоров союзников", "here": True})
            ]
        },
        DONE,
        DONE,
    ]
    act(game_client, player, cid, "Иду в склеп вместе с союзниками")
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    finish_jobs()

    start = len(llm.requests)
    llm.replies.clear()
    narration_text = "Союзники обсуждают защиту склепа."
    llm.replies += [
        {
            "tool_calls": [
                (
                    "roll_check",
                    {
                        "character_id": hid,
                        "stat": "perception",
                        "difficulty": "dc.easy",
                        "reason": "осмотреть союзный склеп",
                    },
                )
            ]
        },
        DONE,
        DONE,
    ]
    act(game_client, player, cid, "Осматриваю союзный склеп")
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    finish_jobs()
    decision = next(
        r
        for r in llm.requests[start:]
        if any(t.get("function", {}).get("name") == "roll_check" for t in r.get("tools") or [])
    )
    system = next(m["content"] for m in decision["messages"] if m.get("role") == "system")
    assert NEW_TITLE in system
    with connect(game_client, player, cid) as (_, before):
        location = before["payload"]["scene"]["location"]
        assert location["name"] == "Затопленный склеп"

    calls_before = len(_director_calls(settings, cid))
    fresh = ScriptedLLM([])
    with TestClient(create_app(settings, llm=fresh, dice_factory=lambda: QueueDice([20]))) as again:
        again.portal.call(again.app.state.master.recover)
        _settle(settings, cid)
        with connect(again, player, cid) as (_, after):
            assert after["payload"]["scene"]["location"] == location
            assert any(m["content"] == "Союзники обсуждают защиту склепа." for m in after["payload"]["messages"])
    assert _node_title(settings, cid) == NEW_TITLE
    assert _works(settings, cid)[0].receipt_event_id == first_work.receipt_event_id
    assert len(_director_calls(settings, cid)) == calls_before
    assert fresh.director_requests == [] and len(asked) >= 1
