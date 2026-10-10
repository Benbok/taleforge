import pytest

from app.core.resolution.contracts import FailureInfo, ResolutionResult
from app.db.models import MasterTurn
from app.tools.master.adjudication import AdjudicationArgs, adjudicate_action
from app.tools.registry import ToolError
from app.tools.resolution.operations import ResolutionProposal
from app.tools.resolution.requests import record_attempt
from tests.resolution_helpers import prepare_action
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


@pytest.mark.parametrize("category,allowed", [("unsupported", True), ("unknown", False), ("rule_denial", False)])
def test_server_classified_failure_only(game, category, allowed):
    settings, campaign_id, hero = game

    async def check(ctx):
        ctx.session.add(MasterTurn(id=ctx.turn_id, campaign_id=campaign_id, status="running", trace={"place": "keep"}))
        await ctx.session.flush()
        ref = await prepare_action(ctx, hero, [{"verb": "interact"}])
        attempt = await record_attempt(
            ctx,
            ref,
            "noncombat.interaction",
            ResolutionResult(
                execution="denied", failure=FailureInfo(code="test", category=category, rolled_back=True, attempt_id="")
            ),
        )
        proposed = ResolutionProposal(
            ref=ref,
            origin="fallback",
            outcome="partial",
            reason="другая возможность",
            attempt_id=attempt,
            operations=[{"kind": "time", "args": {"amount": 1, "unit": "minute", "reason": "цена"}}],
        )
        ctx.remaining_resolution_calls = 8
        before = ctx.world.scene.game_time
        if allowed:
            result = await adjudicate_action(ctx, AdjudicationArgs(proposal=proposed))
            assert result["execution"] == "applied"
            assert ctx.world.scene.game_time == before + 60
        else:
            with pytest.raises(ToolError):
                await adjudicate_action(ctx, AdjudicationArgs(proposal=proposed))
            assert ctx.world.scene.game_time == before

    play(settings, campaign_id, [], check)


def test_no_tool_call_does_not_grant_fallback(game):
    settings, campaign_id, hero = game

    async def check(ctx):
        ctx.session.add(MasterTurn(id=ctx.turn_id, campaign_id=campaign_id, status="running"))
        await ctx.session.flush()
        ref = await prepare_action(ctx, hero, [{"verb": "talk"}])
        args = AdjudicationArgs(
            proposal=ResolutionProposal(
                ref=ref, origin="fallback", outcome="success", reason="test", attempt_id="invented"
            )
        )
        with pytest.raises(ToolError):
            await adjudicate_action(ctx, args)

    play(settings, campaign_id, [], check)


@pytest.mark.parametrize("change", ["success", "cross_turn", "budget", "combat", "other_part"])
def test_grant_constraints(game, change):
    from app.tools.resolution.requests import eligible_adjudications

    settings, campaign_id, hero = game

    async def check(ctx):
        ctx.session.add(MasterTurn(id=ctx.turn_id, campaign_id=campaign_id, status="running"))
        await ctx.session.flush()
        ref = await prepare_action(ctx, hero, [{"verb": "interact"}, {"verb": "talk"}])
        from app.db.models import Message
        from app.tools.resolution.requests import bind_message_actions

        message = await ctx.session.get(Message, ref.source_id)
        ctx.required_actions = bind_message_actions(message, hero)
        attempt = await record_attempt(
            ctx,
            ref,
            "noncombat.interaction",
            ResolutionResult(
                execution="denied",
                failure=FailureInfo(code="test", category="unsupported", rolled_back=True, attempt_id=""),
            ),
        )
        args = AdjudicationArgs(
            proposal=ResolutionProposal(
                ref=ref, origin="fallback", outcome="partial", reason="test", attempt_id=attempt
            )
        )
        ctx.remaining_resolution_calls = 8
        if change == "success":
            await record_attempt(
                ctx, ref, "noncombat.interaction", ResolutionResult(execution="applied", game_outcome="failure")
            )
            assert not await eligible_adjudications(ctx)
        elif change == "cross_turn":
            message.turn_id = "other_turn"
        elif change == "budget":
            ctx.remaining_resolution_calls = 0
        elif change == "combat":
            ctx.world.scene.mode = "combat"
        if change == "other_part":
            await adjudicate_action(ctx, args)
            assert hero not in ctx.closed
        else:
            with pytest.raises(ToolError):
                await adjudicate_action(ctx, args)

    play(settings, campaign_id, [], check)
