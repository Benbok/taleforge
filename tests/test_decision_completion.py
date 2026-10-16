"""Completion is proved by all action parts and obligations, never an actor closed flag."""

# ruff: noqa: F811 -- shared fixtures
from types import SimpleNamespace as NS

import pytest

from app.core.resolution.contracts import ActionProgress, ActionRef, ResolutionResult
from app.tools.resolution.requests import action_key
from tests.test_master import admin_g, dice, game_client, llm  # noqa: F401


def context():
    ref = ActionRef(campaign_id="c", source_kind="message", source_id="m", actor_id="hero", part=0)
    ctx = NS(
        required_actions=[ref],
        action_progress={action_key(ref): ActionProgress(status="completed")},
        closed={"hero"},
        events=[],
        turn_diagnostics={},
        world=NS(characters={"hero": NS()}, actor=lambda _: NS(alive=True)),
    )
    return ctx, ref


def check(ctx, **overrides):
    from app.agents.master.decision_completion import check_decision_completion

    args = {
        "trace_calls": [],
        "required_actors": {"hero"},
        "opening_actors": set(),
        "pending": dict.fromkeys(("transition", "spawn", "reaction", "world_response", "plot"), False),
    }
    args.update(overrides)
    return check_decision_completion(ctx, **args)


def test_terminal_miss_finishes_without_reroll():
    ctx, ref = context()
    ctx.action_progress[action_key(ref)] = ActionProgress(
        status="completed", result=ResolutionResult(execution="applied", game_outcome="failure")
    )
    assert check(ctx).can_finish


def test_every_part_and_actor_must_be_terminal():
    ctx, ref = context()
    second = ref.model_copy(update={"part": 1})
    ctx.required_actions.append(second)
    assert not check(ctx).can_finish  # ctx.closed already contains hero
    ctx.action_progress[action_key(second)] = ActionProgress(status="completed")
    assert check(ctx).can_finish
    assert not check(ctx, required_actors={"hero", "other"}).can_finish
    assert not check(ctx, required_actors=set()).can_finish
    ctx.required_actions = []
    assert not check(ctx).can_finish


@pytest.mark.parametrize("key", ["transition", "spawn", "reaction", "world_response", "plot"])
def test_pending_obligation_prevents_completion(key):
    ctx, _ = context()
    pending = dict.fromkeys(("transition", "spawn", "reaction", "world_response", "plot"), False)
    pending[key] = True
    assert not check(ctx, pending=pending).can_finish
    del pending[key]
    assert not check(ctx, pending=pending).can_finish


def test_unknown_pending_is_conservative():
    ctx, _ = context()
    assert not check(ctx, pending={"unknown": False}).can_finish


def test_critical_failure_waits_for_consequence():
    ctx, _ = context()
    call = {
        "tool": "roll_check",
        "args": {"character_id": "hero"},
        "result": {"ok": True, "result": {"critical": "fail"}},
    }
    assert not check(ctx, trace_calls=[call]).can_finish
    effect = {"tool": "apply_effect", "args": {"target_id": "hero"}, "result": {"ok": True}}
    assert check(ctx, trace_calls=[call, effect]).can_finish


def test_search_success_waits_for_world_finding():
    ctx, ref = context()
    ctx.turn_diagnostics["search_checks"] = {action_key(ref): "event_search"}
    ctx.events = [
        NS(
            tool="roll_check",
            id="event_search",
            actor_id="hero",
            target_id=None,
            payload={"kind": "check", "success": True, "stat": "perception"},
        )
    ]
    assert not check(ctx).can_finish
    ctx.events.append(NS(tool="learn_fact", actor_id="hero", target_id=None, payload={}))
    assert check(ctx).can_finish


@pytest.mark.parametrize("scenario,expected", [("routed_attack", 0), ("native", 1), ("speech", 1)])
def test_early_finish_model_calls_keep_real_effects(game_client, admin_g, llm, dice, settings, scenario, expected):
    from app.db.models import Campaign, Event, InventoryItem, LlmCall, MasterTurn
    from tests.game import party, run
    from tests.test_combat import _setup
    from tests.test_master import DONE, act, rows

    campaign, (player,), hero = party(game_client, admin_g)
    cid = campaign["id"]

    async def enable(s):
        c = await s.get(Campaign, cid)
        c.settings = {**c.settings, "llm_optimization": {"early_finish": True}}
        await s.commit()

    run(settings, enable)
    if scenario == "routed_attack":
        enemy = _setup(settings, cid, hero["id"], "creature.goblin", zone="melee", first="hero", hp=1)
        weapon = next(
            i.id
            for i in rows(settings, InventoryItem, InventoryItem.character_id == hero["id"])
            if i.item_template_id == "item.longsword"
        )
        parsed = {"actions": [{"index": 0, "verb": "attack", "target_id": enemy, "instrument_id": weapon}]}
        steps = []
        dice += [18, 8]
    elif scenario == "native":
        parsed = {"actions": [{"index": 0, "verb": "interact", "summary": "Wave"}]}
        steps = [{"tool_calls": [("auto_success", {"character_id": hero["id"], "reason": "wave"})]}]
    else:
        parsed = {"kind": "speech", "actions": []}
        steps = [DONE]
    llm.replies += [
        {"tool_calls": [("submit_intent", parsed)]},
        *steps,
        {"text": "Подтверждённый исход описан."},
        {"text": "Подтверждённый исход описан."},
    ]
    assert act(game_client, player, cid, "Действую" if scenario != "speech" else "Привет!")["kind"] == "narration"
    turns = rows(settings, MasterTurn, MasterTurn.campaign_id == cid)
    turn = turns[-1]
    assert len(rows(settings, LlmCall, LlmCall.turn_id == turn.id, LlmCall.purpose == "decide")) == expected
    if scenario != "speech":
        assert turn.trace["decision_stop_reason"] == "resolved_actions"
        assert not rows(settings, Event, Event.turn_id == turn.id, Event.tool == "cancel_action")
    if scenario == "routed_attack":
        assert len(rows(settings, Event, Event.turn_id == turn.id, Event.tool == "resolve_attack")) == 1


def test_creative_talk_finishes_without_automatic_cancellation(game_client, admin_g, llm, settings):
    import json

    from app.agents.master.optimization import FLAGS
    from app.db.models import Campaign, Event, LlmCall, MasterTurn, Message
    from app.tools.registry import execute
    from tests.game import party, run
    from tests.test_master import act, rows
    from tests.test_tools import play

    campaign, (player,), hero = party(game_client, admin_g)
    cid = campaign["id"]

    async def enable(s):
        c = await s.get(Campaign, cid)
        c.settings = {**c.settings, "llm_optimization": dict.fromkeys(FLAGS, True)}
        await s.commit()

    async def scene(ctx):
        assert (await execute(ctx, "create_location", {"name": "Tavern", "make_current": True}))["ok"]

    run(settings, enable)
    play(settings, cid, [], scene)

    def decide(messages, tools):
        marker = "Текущие части заявок (используй точный action_ref):\n"
        note = next(m["content"] for m in reversed(messages) if marker in m.get("content", ""))
        parts = json.JSONDecoder().raw_decode(note.split(marker, 1)[1])[0]
        return {
            "tool_calls": [
                (
                    "adjudicate_action",
                    {
                        "proposal": {
                            "ref": parts[0]["ref"],
                            "origin": "creative",
                            "outcome": "success",
                            "reason": "The bartender hears the request",
                            "operations": [],
                        }
                    },
                )
            ]
        }

    llm.replies += [
        {"tool_calls": [("submit_intent", {"actions": [{"verb": "talk"}]})]},
        decide,
        {"text": "The bartender answers."},
        {"text": "The bartender answers."},
    ]
    act(game_client, player, cid, "Ask the bartender for a drink")
    (turn,) = rows(settings, MasterTurn, MasterTurn.campaign_id == cid)
    assert turn.status == "done"
    assert turn.trace["decision_stop_reason"] == "resolved_actions"
    assert not turn.trace.get("audit", {}).get("cancel_fallback")
    assert not rows(settings, Event, Event.turn_id == turn.id, Event.tool == "cancel_action")
    assert len(rows(settings, Event, Event.turn_id == turn.id, Event.tool == "resolve_action")) == 1
    assert len(rows(settings, LlmCall, LlmCall.turn_id == turn.id, LlmCall.purpose == "decide")) == 1
    action = next(m for m in rows(settings, Message, Message.campaign_id == cid) if m.kind == "action")
    assert action.data["resolution_progress"]["0"]["status"] == "completed"
