import copy

import pytest
from pydantic import ValidationError

from app.core.resolution.contracts import ActionRef, normalize_result
from app.tools.registry import ToolError, execute
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


def test_check_failure_is_execution_success():
    raw = {"ok": True, "result": {"success": False}, "event_id": "ev_1"}
    before = copy.deepcopy(raw)
    result = normalize_result(raw, attempt_id="a_1")
    assert result.execution == "applied"
    assert result.game_outcome == "failure"
    assert result.event_ids == ["ev_1"]
    assert raw == before


def test_legacy_tool_error_denies_fallback():
    error = ToolError("legacy refusal")
    assert error.category == "unknown"
    assert error.code == "unclassified"
    result = normalize_result({"ok": False, "error": str(error)}, attempt_id="a_1")
    assert result.execution == "denied"
    assert result.failure.category == "unknown"
    assert not result.failure.rolled_back


def test_invalid_args_have_stable_code(game):
    settings, campaign_id, _ = game

    async def check(ctx):
        return await execute(ctx, "roll_check", {})

    raw = play(settings, campaign_id, [], check)
    result = normalize_result(raw, attempt_id="a_1")
    assert not raw["ok"]
    assert result.failure.code == "invalid_arguments"
    assert result.failure.category == "invalid_arguments"


def test_contract_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ActionRef(campaign_id="c", source_kind="message", source_id="m", actor_id="h", part=0, grant=True)
    with pytest.raises(ValidationError):
        ActionRef(campaign_id="c", source_kind="message", source_id="m", actor_id="h", part=-1)


def test_action_dependency_and_progress_contracts():
    from app.core.resolution.contracts import ActionDependency, ActionProgress, ResolutionResult

    dep = ActionDependency(part=1, requires="applied")
    assert dep.part == 1
    assert dep.requires == "applied"
    assert dep.schema_version == 1

    with pytest.raises(ValidationError):
        ActionDependency(part=-1, requires="applied")
    with pytest.raises(ValidationError):
        ActionDependency(part=0, requires="invalid")

    prog = ActionProgress()
    assert prog.status == "pending"
    assert prog.reason_code is None
    assert prog.result is None
    assert prog.blocked_by == []
    assert prog.schema_version == 1

    custom_prog = ActionProgress(
        status="completed",
        result=ResolutionResult(execution="applied"),
        blocked_by=[0],
        reason_code="custom",
    )
    assert custom_prog.status == "completed"
    assert custom_prog.result.execution == "applied"

    with pytest.raises(ValidationError):
        ActionProgress(status="not_a_valid_status")
    with pytest.raises(ValidationError):
        ActionProgress(unknown_field="extra")
