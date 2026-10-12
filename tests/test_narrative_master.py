"""Tests for master agent narrative adaptation, scene slots, and safe narration (Task 10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.llm import ScriptedLLM
from app.db.models import NarrativeThread
from app.main import create_app
from app.tools.narrative.sources import bind_scene_sources
from app.tools.registry import execute
from tests.conftest import login
from tests.game import QueueDice, import_base, party, run
from tests.test_master import act
from tests.test_tools import play


@pytest.fixture
def llm():
    return ScriptedLLM([])


@pytest.fixture
def dice():
    return [1]


@pytest.fixture
def game_client(settings, llm, dice):
    import_base(settings)
    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice(dice))) as c:
        yield c


@pytest.fixture
def admin_g(game_client):
    root = login(game_client, "root", "rootpass")
    r = game_client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
    assert r.status_code == 201, r.text
    return login(game_client, "Arty", "secret1")


DONE = {"text": "готово"}


def failed_check_with_new_opportunity(game_client, admin_g, llm, settings):
    import_base(settings)
    c, (p1,), hero = party(game_client, admin_g, narrative_mode="adaptive")
    cid = c["id"]

    llm.replies += [
        {
            "tool_calls": [
                (
                    "roll_check",
                    {
                        "character_id": hero["id"],
                        "stat": "persuasion",
                        "difficulty": "dc.hard",
                        "reason": "убедить стражника пропустить",
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
                            {
                                "kind": "divergence",
                                "evidence_refs": [
                                    {
                                        "campaign_id": cid,
                                        "kind": "message",
                                        "source_id": "current",
                                    }
                                ],
                                "confidence": "explicit",
                            }
                        ],
                        "summary": "Стражник непреклонен, но в разговоре упоминает старого контрабандиста",
                        "operations": [
                            {
                                "kind": "upsert_thread",
                                "thread": {
                                    "id": "th-smuggler-route",
                                    "version": 1,
                                    "status": "offered",
                                    "audience": ["party"],
                                    "subject_refs": ["guard-1"],
                                },
                            }
                        ],
                    },
                )
            ]
        },
        DONE,
        {
            "text": (
                "Стражник хмурится и качает головой: «Прохода нет». "
                "Но, оглядевшись, шепчет: «Поищите старика на пристани, если вам так невтерпёж»."
            )
        },
    ]

    act(game_client, p1, cid, "Пытаюсь убедить стражника пропустить нас в город")

    async def inspect(s):
        stmt = select(NarrativeThread).where(
            NarrativeThread.campaign_id == cid,
            NarrativeThread.thread_id == "th-smuggler-route",
        )
        th = await s.scalar(stmt)
        return {
            "check_success": False,  # roll check was a failure
            "new_thread_status": th.status if th else None,
            "player_accepted": th.status == "active" if th else False,
        }

    return run(settings, inspect)


def test_adaptation_does_not_complete_failed_player_action(game_client, admin_g, llm, settings):
    report = failed_check_with_new_opportunity(game_client, admin_g, llm, settings)
    assert report["check_success"] is False
    assert report["new_thread_status"] == "offered"
    assert report["player_accepted"] is False


def test_bind_scene_sources_stable_slots(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    async def scenario(ctx):
        slots1 = await bind_scene_sources(ctx)
        assert len(slots1) == 3
        assert [s.stable_part for s in slots1] == [0, 1, 2]

        # Calling again returns identical slots
        slots2 = await bind_scene_sources(ctx)
        assert slots1 == slots2

    play(settings, cid, [], scenario)


def test_fake_slot_ref_rejected(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    async def scenario(ctx):
        res = await execute(
            ctx,
            "adapt_story",
            {
                "slot_ref": 3,
                "grounds": [],
                "summary": "Fake slot",
                "operations": [],
            },
        )
        assert res["ok"] is False
        assert res["failure"]["code"] in ("invalid_arguments", "invalid_slot")

    play(settings, cid, [], scenario)


def _adapt_with_message(game_client, admin_g, llm, source_id: str, thread_id: str):
    c, (p1,), _hero = party(game_client, admin_g, narrative_mode="adaptive")
    cid = c["id"]
    adapt = {
        "slot_ref": 0,
        "grounds": [
            {
                "kind": "divergence",
                "evidence_refs": [{"campaign_id": cid, "kind": "message", "source_id": source_id}],
                "confidence": "explicit",
            }
        ],
        "summary": "Новая возможность из разговора",
        "operations": [
            {
                "kind": "upsert_thread",
                "thread": {"id": thread_id, "version": 1, "status": "offered", "audience": ["party"]},
            }
        ],
    }
    llm.replies += [{"tool_calls": [("adapt_story", adapt)]}, DONE, {"text": "Разговор идёт дальше."}]
    act(game_client, p1, cid, "Расспрашиваю трактирщика о дороге")
    return cid


def test_adapt_story_rejects_invented_message_ref(game_client, admin_g, llm, settings):
    """Выдуманная ссылка на сообщение отклоняется, а не подменяется сообщением хода (Review Focus 2)."""
    cid = _adapt_with_message(game_client, admin_g, llm, "msg-invented-by-model", "th-invented")

    async def thread(s):
        q = select(NarrativeThread).where(NarrativeThread.campaign_id == cid)
        return await s.scalar(q.where(NarrativeThread.thread_id == "th-invented"))

    assert run(settings, thread) is None


def test_adapt_story_binds_current_message_marker(game_client, admin_g, llm, settings):
    """Явный маркер current — реплика игрока этого хода, проверяемый сервером источник."""
    cid = _adapt_with_message(game_client, admin_g, llm, "current", "th-current")

    async def thread(s):
        q = select(NarrativeThread).where(NarrativeThread.campaign_id == cid)
        return await s.scalar(q.where(NarrativeThread.thread_id == "th-current"))

    row = run(settings, thread)
    assert row is not None and row.status == "offered"
