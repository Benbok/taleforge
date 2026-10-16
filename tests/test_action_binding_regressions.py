import asyncio
from types import SimpleNamespace

import pytest

from app.agents.master.action_binding import bind_tool_action, is_action_compatible
from app.core.resolution.contracts import ActionProgress, ResolutionResult
from app.db.models import Message
from app.tools.registry import ToolError
from app.tools.resolution.requests import action_key, bind_message_actions


def test_use_item_matches_inventory_instrument():
    assert not is_action_compatible(
        "use_item", {"inventory_id": "other"}, {"verb": "use_item", "instrument_id": "requested"}
    )


def test_unlock_matches_requested_passage():
    assert not is_action_compatible(
        "edit_sketch", {"action": "unlock", "target": "other"}, {"verb": "interact", "target_id": "requested"}
    )


def test_binding_enforces_dependency_before_execution():
    message = Message(id="m", campaign_id="c", kind="action", seat_id="seat", intent={"actions": [
        {"verb": "interact"},
        {"verb": "search", "depends_on": [{"part": 0, "requires": "success"}]},
    ]})
    refs = bind_message_actions(message, "hero")

    class Session:
        identity_map = {"m": message}

        async def get(self, model, ident):
            return message

    ctx = SimpleNamespace(
        campaign=SimpleNamespace(id="c", settings={}),
        world=SimpleNamespace(
            characters={"hero": SimpleNamespace(id="hero", seat_id="seat")},
            entities={}, place_of=lambda hero: None, in_fight=lambda ident: False,
        ),
        session=Session(), required_actions=refs, action_progress={},
    )

    async def check():
        with pytest.raises(ToolError, match="предшествующее"):
            await bind_tool_action(ctx, "roll_check", {"character_id": "hero", "stat": "perception"}, refs[1])
        ctx.action_progress[action_key(refs[0])] = ActionProgress(
            status="completed", result=ResolutionResult(execution="applied", game_outcome="success")
        )
        binding = await bind_tool_action(ctx, "roll_check", {"character_id": "hero", "stat": "perception"}, refs[1])
        assert binding.ref == refs[1]

    asyncio.run(check())


def test_finalization_keeps_dependency_reason(monkeypatch):
    from app.agents.master.action_progress import finalize_action_parts

    message = Message(id="m", campaign_id="c", intent={"actions": [
        {"verb": "interact"}, {"verb": "search", "depends_on": [{"part": 0, "requires": "success"}]},
    ]})
    refs = bind_message_actions(message, "hero")
    ctx = SimpleNamespace(required_actions=refs, events=[], turn_diagnostics={}, turn_id=None,
        session=SimpleNamespace(identity_map={"m": message}), action_progress={
            action_key(refs[0]): ActionProgress(status="denied"),
        })

    async def save(ctx, ref, progress):
        ctx.action_progress[action_key(ref)] = progress

    monkeypatch.setattr("app.agents.master.action_progress.set_action_progress", save)
    asyncio.run(finalize_action_parts(ctx))
    assert ctx.action_progress[action_key(refs[1])].status == "blocked"
    assert ctx.action_progress[action_key(refs[1])].blocked_by == [0]


def test_discovery_does_not_close_another_bound_part(monkeypatch):
    from app.agents.master.action_progress import apply_tool_progress
    from app.core.resolution.contracts import ToolActionBinding

    message = Message(id="m", campaign_id="c", intent={"actions": [{"verb": "search"}, {"verb": "search"}]})
    refs = bind_message_actions(message, "hero")
    ctx = SimpleNamespace(required_actions=refs, events=[], action_progress={},
        turn_diagnostics={"search_checks": {action_key(refs[0]): "check0", action_key(refs[1]): "check1"}})
    saved = []

    async def save(ctx, ref, progress):
        saved.append(ref)

    monkeypatch.setattr("app.agents.master.action_progress.set_action_progress", save)
    monkeypatch.setattr("app.agents.master.action_progress.mark_resolved", lambda *args: None)
    asyncio.run(apply_tool_progress(ctx, ToolActionBinding(ref=refs[1], role="consequence"), {
        "ok": True, "tool": "place_item", "event_id": "found", "result": {"discovery_check_event_id": "check0"},
    }))
    assert saved == []


def test_invalid_call_does_not_retain_previous_binding():
    from app.tools.registry import execute

    ctx = SimpleNamespace(current_binding=object())
    result = asyncio.run(execute(ctx, "missing_tool", {}))
    assert not result["ok"]
    assert ctx.current_binding is None
