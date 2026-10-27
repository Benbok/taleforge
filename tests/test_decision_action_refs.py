# ruff: noqa: F811 -- shared integration fixtures
"""Decision references remain real, owned, and bounded on repair."""

import json

import pytest

from app.api.schemas import CampaignCreateIn, CampaignPatchIn
from app.db.models import Message
from app.tools.registry import execute
from app.tools.resolution.requests import bind_message_actions
from tests.test_master import act, admin_g, dice, game_client, llm, rows  # noqa: F401
from tests.test_tools import game, play  # noqa: F401


def test_optimizations_are_integrated_and_ignore_obsolete_campaign_flags():
    from app.agents.master.optimization import optimization_flags

    defaults = optimization_flags({})
    assert len(defaults) == 6 and all(defaults.values())
    for obsolete in ({"action_refs": False}, dict.fromkeys(defaults, False), [], None):
        assert optimization_flags({"llm_optimization": obsolete}) == defaults


@pytest.mark.parametrize("schema", [CampaignCreateIn, CampaignPatchIn])
@pytest.mark.parametrize("flags", [{"unknown": True}, {"action_refs": "true"}, {"action_refs": 1}, []])
def test_campaign_schema_has_no_optimization_switch(schema, flags):
    parsed = schema.model_validate({"name": "Game", "llm_optimization": flags})
    assert "llm_optimization" not in parsed.model_dump()
    assert "llm_optimization" not in schema.model_json_schema()["properties"]


async def source(ctx, hero, actions):
    message = Message(
        campaign_id=ctx.campaign.id,
        seat_id=ctx.world.characters[hero].seat_id,
        kind="action",
        seq=100,
        content="request",
        intent={"actions": actions},
    )
    ctx.session.add(message)
    await ctx.session.flush()
    refs = bind_message_actions(message, hero)
    ctx.required_actions = refs
    return message, refs


def test_action_context_exposes_all_parts_without_admission(game):
    from app.agents.master.resolution import action_context_prompt

    settings, cid, hero = game

    async def check(ctx):
        message, refs = await source(
            ctx,
            hero,
            [
                {"verb": "move", "summary": "Walk"},
                {"verb": "attack", "summary": "Hit", "depends_on": [{"part": 0, "requires": "success"}]},
            ],
        )
        note = await action_context_prompt(ctx)
        assert message.id in note and "Walk" in note and "Hit" in note
        for ref in refs:
            assert json.dumps(ref.model_dump(), ensure_ascii=False) in note
        parts = json.loads(note.rsplit("\n", 1)[1])
        assert [part["status"] for part in parts] == ["pending", "pending"]
        assert parts[1]["depends_on"] == [{"part": 0, "requires": "success"}]
        ctx.required_actions = []
        assert "source_id" not in await action_context_prompt(ctx)

    play(settings, cid, [], check)


@pytest.mark.parametrize(
    "stored,expected",
    [
        ({"resolution_progress": {"0": {"status": "completed"}}}, "completed"),
        ({"resolution_progress": {"0": {"status": "denied"}}}, "denied"),
        ({"resolution_completed": {"0": {"execution": "applied", "game_outcome": "success"}}}, "completed"),
    ],
)
def test_action_context_recovers_persisted_status(game, stored, expected):
    from app.agents.master.resolution import action_context_prompt

    settings, cid, hero = game

    async def check(ctx):
        message, _refs = await source(ctx, hero, [{"verb": "interact", "summary": "Wave"}])
        message.data = {**message.data, **stored}
        assert not ctx.action_progress
        parts = json.loads((await action_context_prompt(ctx)).rsplit("\n", 1)[1])
        assert parts[0]["status"] == expected

    play(settings, cid, [], check)


@pytest.mark.parametrize("surplus", [{"source_id": "current"}, "nonsense", {"campaign_id": "other"}])
def test_read_only_ignores_surplus_ref_but_mutation_rejects(game, surplus):
    settings, cid, hero = game

    async def check(ctx):
        result = await execute(ctx, "get_scene", {"action_ref": surplus})
        assert result["ok"], result
        result = await execute(ctx, "auto_success", {"character_id": hero, "reason": "ok", "action_ref": surplus})
        assert not result["ok"]

    play(settings, cid, [], check)


def test_explicit_source_checks_owner_even_without_required_actions(game):
    settings, cid, hero = game

    async def check(ctx):
        message, (ref,) = await source(ctx, hero, [{"verb": "interact"}])
        ctx.required_actions = []
        message.seat_id = None
        result = await execute(
            ctx, "auto_success", {"character_id": hero, "reason": "ok", "action_ref": ref.model_dump()}
        )
        assert not result["ok"] and result["failure"]["code"] == "invalid_source"

    play(settings, cid, [], check)


def test_campaign_api_does_not_store_obsolete_optimization_switch(game_client, admin_g):
    created = game_client.post(
        "/api/campaigns", headers=admin_g, json={"name": "Flags", "llm_optimization": {"action_refs": True}}
    )
    assert created.status_code == 201, created.text
    campaign = created.json()
    assert "llm_optimization" not in campaign["settings"]
    changed = game_client.patch(
        f"/api/campaigns/{campaign['id']}",
        headers=admin_g,
        json={"llm_optimization": {"action_refs": False, "role_context": True}},
    )
    assert changed.status_code == 200, changed.text
    assert "llm_optimization" not in changed.json()["settings"]
    for invalid in ({"unknown": True}, {"action_refs": "false"}):
        rejected = game_client.patch(
            f"/api/campaigns/{campaign['id']}", headers=admin_g, json={"llm_optimization": invalid}
        )
        assert rejected.status_code == 200
        assert "llm_optimization" not in rejected.json()["settings"]
