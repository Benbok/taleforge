# ruff: noqa: F811 -- shared integration fixtures
"""Decision references remain real, owned, and bounded on repair."""

import json

import pytest
from pydantic import ValidationError

from app.api.schemas import CampaignCreateIn, CampaignPatchIn
from app.db.models import Campaign, Character, Event, MasterTurn, Message, Scene
from app.tools.registry import execute
from app.tools.resolution.requests import bind_message_actions
from tests.game import QueueDice, party, run
from tests.test_master import act, admin_g, dice, game_client, llm, rows  # noqa: F401
from tests.test_tools import game, play  # noqa: F401


def test_optimization_flags_are_strict_and_disabled_by_default():
    from app.agents.master.optimization import optimization_flags

    defaults = optimization_flags({})
    assert len(defaults) == 6 and not any(defaults.values())
    assert optimization_flags({"llm_optimization": {"action_refs": True}})["action_refs"]
    for invalid in ({"unknown": True}, {"action_refs": 1}, {"action_refs": "false"}, []):
        with pytest.raises(ValueError):
            optimization_flags({"llm_optimization": invalid})


@pytest.mark.parametrize("schema", [CampaignCreateIn, CampaignPatchIn])
@pytest.mark.parametrize("flags", [{"unknown": True}, {"action_refs": "true"}, {"action_refs": 1}, []])
def test_campaign_settings_reject_invalid_optimization(schema, flags):
    with pytest.raises(ValidationError):
        schema.model_validate({"name": "Game", "llm_optimization": flags})


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


def test_campaign_optimization_settings_round_trip(game_client, admin_g):
    created = game_client.post(
        "/api/campaigns", headers=admin_g, json={"name": "Flags", "llm_optimization": {"action_refs": True}}
    )
    assert created.status_code == 201, created.text
    campaign = created.json()
    assert campaign["settings"]["llm_optimization"] == {"action_refs": True}
    changed = game_client.patch(
        f"/api/campaigns/{campaign['id']}",
        headers=admin_g,
        json={"llm_optimization": {"action_refs": False, "role_context": True}},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["settings"]["llm_optimization"] == {"action_refs": False, "role_context": True}
    for invalid in ({"unknown": True}, {"action_refs": "false"}):
        rejected = game_client.patch(
            f"/api/campaigns/{campaign['id']}", headers=admin_g, json={"llm_optimization": invalid}
        )
        assert rejected.status_code == 422


def test_decision_read_only_ignores_malformed_surplus_ref(game_client, admin_g, llm, settings):
    campaign, (player,), hero = party(game_client, admin_g)
    llm.replies += [
        {"tool_calls": [("submit_intent", {"actions": [{"index": 0, "verb": "interact", "summary": "Wave"}]})]},
        {"tool_calls": [("get_scene", {"action_ref": {"source_id": "current"}})]},
        {"tool_calls": [("auto_success", {"character_id": hero["id"], "reason": "wave"})]},
        {"text": "готово"},
        {"text": "Ты машешь рукой."},
        {"text": "Ты машешь рукой."},
    ]
    act(game_client, player, campaign["id"], "Машу рукой")
    (turn,) = rows(settings, MasterTurn, MasterTurn.campaign_id == campaign["id"])
    assert turn.status == "done", turn.error
    assert next(call for call in turn.trace["calls"] if call["tool"] == "get_scene")["result"]["ok"]


@pytest.mark.parametrize("tool", ["resolve_attack", "cast_spell"])
def test_hostile_routes_validate_ref_before_initiative(game_client, admin_g, llm, settings, tool):
    from app.tools.runtime import open_context

    campaign, (player,), hero = party(game_client, admin_g)
    cid = campaign["id"]

    async def prepare(s):
        c = await s.get(Campaign, cid)
        c.settings = {**c.settings, "llm_optimization": {"action_refs": True}}
        ctx = await open_context(s, c, QueueDice([]), turn_id=None, seat_id=None)
        ch = ctx.world.characters[hero["id"]]
        ch.sheet = {**ch.sheet, "class_id": "class.wizard", "prepared": ["spell.magic_missile"]}
        ch.resources = {**ch.resources, "slots": {"1": {"total": 2, "used": 0}}}
        # A real other actor makes the mismatch an ownership error, not an unknown-id error.
        other = Character(
            campaign_id=cid, name="Other", status="active", sheet=ch.sheet, resources={}, location_id=ch.location_id
        )
        s.add(other)
        await s.flush()
        result = await execute(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Enemy"})
        assert result["ok"], result
        enemy = result["result"]["spawned"][0]["id"]
        await s.commit()
        return other.id, enemy

    other, enemy = run(settings, prepare)

    def invalid_call(messages, _tools):
        content = messages[1]["content"].split("Текущие части заявок (используй точный action_ref):\n", 1)[1]
        parts, _ = json.JSONDecoder().raw_decode(content)
        ref = {**parts[0]["ref"], "actor_id": other}
        args = (
            {"attacker_id": hero["id"], "target_id": enemy, "attack": "item.longsword"}
            if tool == "resolve_attack"
            else {"caster_id": hero["id"], "spell_id": "spell.magic_missile", "target_ids": [enemy]}
        )
        return {"tool_calls": [(tool, {**args, "action_ref": ref})]}

    llm.replies += [
        {"tool_calls": [("submit_intent", {"actions": [{"index": 0, "verb": "interact", "summary": "Wave"}]})]},
        invalid_call,
        invalid_call,
        {"text": "Действие не выполнено."},
        {"text": "Действие не выполнено."},
    ]
    act(game_client, player, cid, "Машу рукой")
    (turn,) = rows(settings, MasterTurn, MasterTurn.campaign_id == cid)
    assert turn.status == "done", turn.error
    assert hero["id"] not in turn.trace["closed"] or all(
        c["tool"] == "cancel_action" or not c["result"].get("ok") for c in turn.trace["calls"]
    )
    assert not rows(settings, Event, Event.campaign_id == cid, Event.tool.in_(["set_scene_mode", tool]))
    (scene,) = rows(settings, Scene, Scene.campaign_id == cid)
    assert scene.mode == "free" and not (scene.state or {}).get("combat")
    (ch,) = rows(settings, Character, Character.id == hero["id"])
    assert ch.resources["slots"]["1"]["used"] == 0


def test_invalid_sources_have_one_repair_and_stop_batch(game_client, admin_g, llm, settings):
    campaign, (player,), hero = party(game_client, admin_g)
    cid = campaign["id"]

    async def enable(s):
        c = await s.get(Campaign, cid)
        c.settings = {**c.settings, "llm_optimization": {"action_refs": True}}
        await s.commit()

    run(settings, enable)

    def bad(ref):
        return {"campaign_id": cid, "source_kind": "message", "source_id": ref, "actor_id": hero["id"], "part": 0}

    llm.replies += [
        {"tool_calls": [("submit_intent", {"actions": [{"index": 0, "verb": "interact", "summary": "Wave"}]})]},
        {
            "tool_calls": [
                ("auto_success", {"character_id": hero["id"], "reason": "wave", "action_ref": bad("current")})
            ]
        },
        {
            "tool_calls": [
                ("auto_success", {"character_id": hero["id"], "reason": "wave", "action_ref": bad("msg_current")}),
                ("place_item", {"item_template_id": "item.dagger", "reason": "must be skipped"}),
                ("get_scene", {}),
            ]
        },
        {"text": "Действие не выполнено."},
        {"text": "Действие не выполнено."},
    ]
    told = act(game_client, player, cid, "Машу рукой")
    (turn,) = rows(settings, MasterTurn, MasterTurn.campaign_id == cid)
    assert turn.status == "done", turn.error
    assert turn.trace["invalid_source_repairs"] == 1
    assert (
        len(
            [
                r
                for r in llm.requests
                if r.get("tools") and any(t["function"]["name"] == "auto_success" for t in r["tools"])
            ]
        )
        == 2
    )
    assert not rows(settings, Event, Event.campaign_id == cid, Event.tool == "place_item")
    assert not any(c["tool"] == "get_scene" and not c["result"].get("skipped") for c in turn.trace["calls"])
    assert "не выполнено" in told["content"].lower()
    (message,) = rows(settings, Message, Message.campaign_id == cid, Message.kind == "action")
    progress = message.data["resolution_progress"]["0"]
    assert progress["status"] != "completed"
    cancels = [call for call in turn.trace["calls"] if call["tool"] == "cancel_action"]
    assert len(cancels) == 1 and cancels[0]["result"]["ok"]
