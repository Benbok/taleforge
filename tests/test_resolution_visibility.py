from app.agents.master.outcomes import public_attempts, transition_outcome


def test_fallback_success_does_not_mask_other_failed_transition():
    attempts = [
        {"tool": "enter_room", "request_key": "other", "result": {"ok": False, "error": "secret"}},
        {
            "tool": "adjudicate_action",
            "request_key": "first",
            "result": {
                "ok": True,
                "result": {"execution": "applied", "game_outcome": "partial", "reason": "secret motive"},
            },
        },
    ]
    assert transition_outcome(attempts) == "failed"
    public = public_attempts(attempts)
    assert "adjudicate_action" in public
    assert "secret" not in public


def test_scoped_transition_failure_survives_other_success():
    attempts = [
        {"tool": "enter_room", "request_key": "first", "result": {"ok": False}},
        {"tool": "enter_room", "request_key": "other", "result": {"ok": True}},
    ]
    assert transition_outcome(attempts) == "failed"


def test_private_outcome_is_not_visible_to_other_group():
    from types import SimpleNamespace

    from app.agents.master.outcomes import public_resolution
    from app.core.resolution.contracts import ResolutionResult

    ctx = SimpleNamespace(world=SimpleNamespace(crew={"ch_1"}))
    result = ResolutionResult(execution="applied", game_outcome="partial", event_ids=["secret_id"])
    assert public_resolution(ctx, result, {"ch_2"}) == {}
    assert public_resolution(ctx, result, {"ch_1"}) == {"execution": "applied", "game_outcome": "partial"}
