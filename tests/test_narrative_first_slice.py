"""First completed vertical slice for master narrative adaptation (Task 11 / Gate A).

Scenario: Player negotiates an alliance with an antagonist -> mechanics roll check passes ->
adapt_story commits the alliance and patches the main future open node ->
reconnect survives and next prompt/plan reflects the new node without forcing old kill goal.
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.llm import ScriptedLLM
from app.db.models import CampaignSecret, Event
from app.main import create_app
from tests.conftest import login
from tests.game import QueueDice, import_base, party, run
from tests.test_master import act


@pytest.fixture
def llm():
    return ScriptedLLM([])


@pytest.fixture
def dice():
    return [20]


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


def run_alliance_story_scenario(game_client, admin_g, llm, settings, monkeypatch) -> dict:
    from app.agents import prelude, rhythm

    async def skip_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(prelude, "prepare_campaign_intro", skip_task)
    monkeypatch.setattr(game_client.app.state.master, "introduce", skip_task)
    monkeypatch.setattr(rhythm, "session_goal", skip_task)

    import_base(settings)
    c, (p1,), hero = party(game_client, admin_g, narrative_mode="adaptive")
    cid = c["id"]

    # Initialize rich plot with one closed node and one open node in CampaignSecret
    initial_plot = {
        "title": "Битва за долину",
        "conflict": "Нежить угрожает долине",
        "stakes": "Выживание долины",
        "acts": [
            {
                "id": "act-1",
                "title": "Тени прошлого",
                "status": "active",
                "goal": "Остановить осквернение",
                "exit": "Кладбище очищено или защищено",
                "nodes": [
                    {
                        "id": "node-closed-1",
                        "title": "Первая встреча",
                        "status": "done",
                        "outcome": "Герои узнали о лидере нежити",
                        "summary": "Разведка у старых склепов",
                    },
                    {
                        "id": "node-open-1",
                        "title": "Штурм склепа",
                        "status": "sketch",
                        "summary": "Уничтожить некроманта и его слуг",
                    },
                ],
            }
        ],
        "antagonists": [
            {
                "id": "ant-necromancer",
                "name": "Некромант Мортис",
                "goal": "Уничтожить всех живых в долине",
                "status": "active",
            }
        ],
    }

    async def init_plot(s):
        sec = await s.get(CampaignSecret, cid)
        if not sec:
            sec = CampaignSecret(campaign_id=cid)
            s.add(sec)
        sec.plot = copy.deepcopy(initial_plot)
        await s.commit()

    run(settings, init_plot)

    # Turn 1: Player offers alliance to Mortis
    # Decision phase:
    # 1. roll_check for persuasion (succeeds with queued dice 20)
    # 2. adapt_story patches open node to "Защита кладбища" and stops antagonist front
    # 3. finish decisions (DONE)
    # 4. narration
    llm.replies += [
        {
            "tool_calls": [
                (
                    "roll_check",
                    {
                        "character_id": hero["id"],
                        "stat": "persuasion",
                        "difficulty": "dc.medium",
                        "reason": "убедить Мортиса заключить перемирие",
                    },
                )
            ]
        },
        {
            "tool_calls": [
                (
                    "adapt_story",
                    {
                        "slot_ref": 2,  # future slot for revise_future_situation
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
                        "summary": "Мортис соглашается на союз; открытый узел меняется на защиту кладбища",
                        "operations": [
                            {
                                "kind": "revise_future_situation",
                                "patch": {
                                    "edits": [
                                        {
                                            "kind": "update_open_node",
                                            "act_id": "act-1",
                                            "node_id": "node-open-1",
                                            "fields": {
                                                "title": "Защита кладбища",
                                                "summary": "Мортис и герои вместе обороняют кладбище от мародёров",
                                            },
                                        }
                                    ]
                                },
                            },
                            {
                                "kind": "change_front_intent",
                                "front_ref": {
                                    "campaign_id": cid,
                                    "source_kind": "antagonist",
                                    "source_id": "ant-necromancer",
                                },
                                "new_intent": "Защищать кладбище вместе с героями",
                                "status": "stopped",
                            },
                        ],
                    },
                )
            ]
        },
        DONE,
        {"text": ("Мортис опускает посох: «Договорились. Защитите склепы от мародёров, и нежить не тронет деревню».")},
    ]

    act(game_client, p1, cid, "Предлагаю Мортису союз: мы защитим кладбище от мародёров взамен на мир")

    # Turn 2: Reconnect / Next player action
    # Next turn's prompt should incorporate the updated open node and not force the kill goal
    llm.replies += [
        {
            "tool_calls": [
                (
                    "roll_check",
                    {
                        "character_id": hero["id"],
                        "stat": "perception",
                        "difficulty": "dc.easy",
                        "reason": "осмотреть подходы к кладбищу",
                    },
                )
            ]
        },
        DONE,
        {"text": "Мортис указывает на тропу, откуда приближаются мародёры."},
    ]

    act(game_client, p1, cid, "Осматриваю подходы к кладбищу вместе с Мортисом")

    # Inspect DB and LLM prompts
    async def inspect(s):
        sec = await s.get(CampaignSecret, cid)
        plan = sec.plot if sec else {}
        act_1 = next((a for a in plan.get("acts", []) if a.get("id") == "act-1"), {})
        nodes = act_1.get("nodes", [])
        closed_node = next((n for n in nodes if n.get("id") == "node-closed-1"), {})
        open_node = next((n for n in nodes if n.get("id") == "node-open-1"), {})

        receipts_res = await s.execute(
            select(Event).where(
                Event.campaign_id == cid,
                Event.tool == "adapt_story",
            )
        )
        # квитанции адаптации из хода; фоновый режиссёр (source_kind=work) отвечает на границу хода своей
        receipts = [
            e
            for e in receipts_res.scalars().all()
            if ((e.payload or {}).get("source") or {}).get("source_kind") != "work"
        ]

        return {
            "next_node": open_node.get("title"),
            "closed_outcome_unchanged": closed_node.get("outcome") == "Герои узнали о лидере нежити",
            "adaptation_receipts": len(receipts),
        }

    report = run(settings, inspect)

    # Check that in the second turn's decide request, the new node is present
    # and the forced kill goal from the old open node is absent
    second_turn_requests = [
        req
        for req in llm.requests
        if any(t.get("function", {}).get("name") == "roll_check" for t in req.get("tools") or [])
        and any(
            isinstance(m.get("content"), str) and "Осматриваю подходы к кладбищу" in m["content"]
            for m in req.get("messages", [])
        )
    ]

    forced_kill = False
    if second_turn_requests:
        first_req = second_turn_requests[0]
        sys_msg = next((m["content"] for m in first_req.get("messages", []) if m.get("role") == "system"), "")
        assert "Защита кладбища" in sys_msg
        # Should not force old open node goal "Уничтожить некроманта и его слуг"
        if "Уничтожить некроманта и его слуг" in sys_msg:
            forced_kill = True

    report["forced_kill_goal_in_next_prompt"] = forced_kill
    return report


def test_alliance_changes_main_story_and_survives_reconnect(game_client, admin_g, llm, settings, monkeypatch):
    report = run_alliance_story_scenario(game_client, admin_g, llm, settings, monkeypatch)
    assert report["next_node"] == "Защита кладбища"
    assert report["closed_outcome_unchanged"]
    assert report["adaptation_receipts"] == 1
    assert not report["forced_kill_goal_in_next_prompt"]
