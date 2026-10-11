from app.agents.master.outcomes import public_attempts, transition_outcome
from tests.test_tools import game as game_fixture

game = game_fixture


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
    assert "частичный исход" in public
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


def test_resolution_receipt_diagnostics_never_enter_narrator_results():
    from types import SimpleNamespace

    from app.agents.master.helpers import _render_results
    from app.db.models import Event

    event = Event(
        tool="resolve_action", hidden=True, payload={"reason": "secret diagnostic", "attempt_id": "ra_secret"}
    )
    assert _render_results(SimpleNamespace(events=[event])) == ""


def test_private_group_fact_is_not_in_common_narration(game):
    from app.agents.master.helpers import _render_results
    from app.core.resolution.contracts import Admission
    from app.db.models import Character
    from app.tools.resolution.executor import execute_resolution
    from app.tools.resolution.operations import ResolutionProposal
    from tests.resolution_helpers import prepare_action
    from tests.test_tools import play

    settings, campaign_id, hero = game

    async def check(ctx):
        peer = Character(
            campaign_id=campaign_id,
            name="Другой герой",
            status="approved",
            location_id=ctx.world.characters[hero].location_id,
        )
        ctx.session.add(peer)
        await ctx.session.flush()
        ctx.world.characters[peer.id] = peer
        ctx.world.crew = {hero, peer.id}
        ref = await prepare_action(ctx, hero, [{"verb": "interact"}])
        proposal = ResolutionProposal(
            ref=ref,
            origin="normal",
            outcome="success",
            reason="test",
            operations=[
                {"kind": "fact", "args": {"subject_id": hero, "character_ids": [hero], "fact": "Тайная записка героя"}}
            ],
        )
        assert (
            await execute_resolution(ctx, proposal, Admission("ordinary", "supported_action"))
        ).execution == "applied"
        event = next(e for e in ctx.events if e.tool == "learn_fact")
        assert event.hidden
        assert "Тайная записка" not in _render_results(ctx)

    play(settings, campaign_id, [], check)
