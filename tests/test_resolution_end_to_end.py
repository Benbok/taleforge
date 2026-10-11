import json

import pytest
from sqlalchemy import func, select

from app.db.models import Event, InventoryItem, MasterTurn
from app.tools import standing
from app.tools.master.adjudication import AdjudicationArgs, adjudicate_action
from app.tools.registry import execute
from app.tools.resolution.operations import ResolutionProposal
from app.tools.resolution.standing import standing_resolution
from tests.game import party
from tests.test_master import act, rows
from tests.test_master import admin_g as admin_fixture
from tests.test_master import dice as dice_fixture
from tests.test_master import game_client as game_client_fixture
from tests.test_master import llm as llm_fixture
from tests.test_resolution_safe_failure import UnavailableDice
from tests.test_tools import play

admin_g = admin_fixture
dice = dice_fixture
game_client = game_client_fixture
llm = llm_fixture


@pytest.mark.parametrize("fail_narration", [False, True])
def test_pipeline_safe_failure_price_commit_reconnect_standing_and_replay(
    game_client, admin_g, llm, settings, fail_narration
):
    campaign, (player,), hero = party(game_client, admin_g)
    cid, hid = campaign["id"], hero["id"]

    async def seed(ctx):
        place = (await execute(ctx, "create_location", {"name": "Улица", "make_current": True}))["result"][
            "location_id"
        ]
        npc = (
            await execute(
                ctx,
                "spawn_entity",
                {
                    "creature_template_id": "creature.commoner",
                    "name": "Путник",
                    "location_id": place,
                    "attitude": "neutral",
                },
            )
        )["result"]["spawned"][0]["id"]
        return place, npc

    place, npc = play(settings, cid, [], seed)
    game_client.app.state.master.dice_factory = lambda: UnavailableDice([])

    def decide(messages, tools):
        note = next(m["content"] for m in reversed(messages) if "Допуски к внебоевому решению" in m.get("content", ""))
        tail = note.split("Допуски к внебоевому решению (не переигрывают провал броска):\n", 1)[1]
        grant = json.JSONDecoder().raw_decode(tail)[0][0]
        return {
            "tool_calls": [
                (
                    "adjudicate_action",
                    {
                        "proposal": {
                            "ref": grant["ref"],
                            "origin": "fallback",
                            "outcome": "partial",
                            "reason": "уделил время путнику",
                            "attempt_id": grant["attempt_id"],
                            "operations": [
                                {"kind": "time", "args": {"amount": 2, "unit": "minute", "reason": "разговор"}},
                                {"kind": "entity_update", "args": {"entity_id": npc, "mood": "заинтересован"}},
                                {
                                    "kind": "deed",
                                    "args": {
                                        "subject_id": npc,
                                        "character_ids": [hid],
                                        "effect": "help",
                                        "weight": "major",
                                        "reason": "уделил время путнику",
                                    },
                                },
                            ],
                        }
                    },
                )
            ]
        }

    llm.replies = [
        {"tool_calls": [("submit_intent", {"actions": [{"verb": "interact", "target_id": npc}], "confidence": 1})]},
        {
            "tool_calls": [
                (
                    "roll_check",
                    {"character_id": hid, "stat": "persuasion", "difficulty": "dc.easy", "reason": "разговор"},
                )
            ]
        },
        decide,
        {"text": "готово"},
        {"text": "Путник выслушивает вас. Разговор занимает несколько минут."},
    ]
    if fail_narration:
        llm.replies.pop()
    narration = act(game_client, player, cid, "Предлагаю помощь путнику")
    if fail_narration:
        assert narration["kind"] == "system"
        turn = next(t for t in rows(settings, MasterTurn) if t.status == "failed")
        assert turn.trace["rolled_back"] is True
        assert turn.trace["resolution_attempts"][0]["result"]["failure"]["code"] == "check_dice_failure"
        assert len(turn.trace["resolution_operations"]) == 3
        assert not [e for e in rows(settings, Event) if e.tool == "resolve_action"]
        log = game_client.get(f"/api/campaigns/{cid}/master-log", headers=admin_g).json()
        assert all(not call["ok"] and call["rolled_back"] for call in log["turns"][0]["calls"])
        return
    assert narration["kind"] == "narration"
    turn = next(t for t in rows(settings, MasterTurn) if t.status == "done")
    root, resolution = turn.trace["calls"][:2]
    assert root["result"]["failure"]["code"] == "check_dice_failure"
    assert root["request_key"] == resolution["request_key"]
    assert resolution["result"]["result"]["execution"] == "applied"
    assert not [e for e in rows(settings, Event) if e.tool == "roll_check"]
    proposal = ResolutionProposal.model_validate(resolution["args"]["proposal"])

    async def reconnect(ctx):
        assert ctx.world.place_of(ctx.world.characters[hid]) == place
        assert ctx.world.entities[npc].location_id == place
        assert ctx.world.entities[npc].state["mood"] == "заинтересован"
        clock = ctx.world.scene.game_time
        assert (await adjudicate_action(ctx, AdjudicationArgs(proposal=proposal)))["execution"] == "repeated"
        assert ctx.world.scene.game_time == clock
        await standing.run_standing(ctx)
        response = ctx.world.scene.state["standing"]["responses"][0]
        gift = standing_resolution(
            ctx,
            response["id"],
            [
                {
                    "kind": "gift",
                    "args": {"character_id": hid, "item_template_id": "item.dagger", "reason": "благодарность"},
                },
            ],
            "подарил кинжал",
        )
        ctx.remaining_resolution_calls = 8
        assert (await adjudicate_action(ctx, AdjudicationArgs(proposal=gift)))["execution"] == "applied"
        count = await ctx.session.scalar(
            select(func.sum(InventoryItem.qty)).where(
                InventoryItem.character_id == hid, InventoryItem.item_template_id == "item.dagger"
            )
        )
        assert (await adjudicate_action(ctx, AdjudicationArgs(proposal=gift)))["execution"] == "repeated"
        assert (
            await ctx.session.scalar(
                select(func.sum(InventoryItem.qty)).where(
                    InventoryItem.character_id == hid, InventoryItem.item_template_id == "item.dagger"
                )
            )
            == count
        )

    play(settings, cid, [], reconnect)
