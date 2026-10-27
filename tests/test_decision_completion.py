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
