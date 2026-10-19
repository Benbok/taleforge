import pytest

from app.core.resolution.contracts import FailureInfo, ResolutionResult
from app.db.models import MasterTurn
from app.tools.master.adjudication import AdjudicationArgs, adjudicate_action
from app.tools.registry import ToolError, execute
from app.tools.resolution.operations import ResolutionProposal
from app.tools.resolution.requests import record_attempt
from tests.resolution_helpers import prepare_action
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


@pytest.mark.parametrize("origin", ["creative", "fallback"])
def test_accepted_adjudication_completes_pending_part_and_replay(game, origin):
    from app.core.resolution.contracts import ActionProgress
    from app.db.models import Message
    from app.tools.resolution.requests import action_key, bind_message_actions, set_action_progress

    settings, campaign_id, hero = game

    async def check(ctx):
        await execute(ctx, "create_location", {"name": "Tavern", "make_current": True})
        ctx.session.add(MasterTurn(id=ctx.turn_id, campaign_id=campaign_id, status="running"))
        await ctx.session.flush()
        ref = await prepare_action(ctx, hero, [{"verb": "talk"}, {"verb": "interact"}])
        ctx.remaining_resolution_calls = 8
        message = await ctx.session.get(Message, ref.source_id)
        ctx.required_actions = bind_message_actions(message, hero)
        for part in ctx.required_actions:
            await set_action_progress(ctx, part, ActionProgress(status="pending"))
        attempt = None
        if origin == "fallback":
            attempt = await record_attempt(
                ctx,
                ref,
                "noncombat.interaction",
                ResolutionResult(
                    execution="denied",
                    failure=FailureInfo(
                        code="unsupported",
                        category="unsupported",
                        rolled_back=True,
                        attempt_id="",
                    ),
                ),
            )
        proposal = ResolutionProposal(
            ref=ref,
            origin=origin,
            outcome="success",
            reason="Ask bartender for a drink",
            attempt_id=attempt,
        )
        raw = await execute(ctx, "adjudicate_action", {"proposal": proposal.model_dump()})
        assert raw["ok"], raw
        assert ctx.action_progress[action_key(ref)].status == "completed"
        assert message.data["resolution_progress"]["0"]["status"] == "completed"
        assert message.data["resolution_progress"]["1"]["status"] == "pending"
        assert hero not in ctx.closed  # Another part must still be handled.
        ctx.action_progress.clear()
        replay = await execute(ctx, "adjudicate_action", {"proposal": proposal.model_dump()})
        assert replay["ok"] and replay["result"]["execution"] == "repeated"
        assert ctx.action_progress[action_key(ref)].status == "completed"

    play(settings, campaign_id, [], check)


def test_ambiguous_ordinary_failure_cannot_be_rewritten_as_creative_success(game):
    from app.agents.master.resolution import capture_attempt
    from app.db.models import Message
    from app.tools.resolution.creative import validate_creative_proposal
    from app.tools.resolution.requests import bind_message_actions

    settings, campaign_id, hero = game

    async def check(ctx):
        ctx.session.add(MasterTurn(id=ctx.turn_id, campaign_id=campaign_id, status="running"))
        await ctx.session.flush()
        ref = await prepare_action(ctx, hero, [{"verb": "inspect"}, {"verb": "talk"}])
        ctx.required_actions = bind_message_actions(await ctx.session.get(Message, ref.source_id), hero)
        ctx.closed.add(hero)
        await capture_attempt(ctx, hero, {"ok": True, "result": {"success": False}})
        assert hero not in ctx.closed
        proposal = ResolutionProposal(ref=ref, origin="creative", outcome="success", reason="test")
        assert (await validate_creative_proposal(ctx, proposal)).route == "deny"

    play(settings, campaign_id, [], check)


def test_invalid_arguments_get_only_one_repair(game):
    from app.agents.master.resolution import permit_repair

    settings, campaign_id, hero = game

    async def check(ctx):
        ctx.session.add(MasterTurn(id=ctx.turn_id, campaign_id=campaign_id, status="running"))
        await ctx.session.flush()
        ref = await prepare_action(ctx, hero, [{"verb": "interact"}])
        ctx.required_actions = [ref]
        bad = ResolutionResult(
            execution="denied",
            failure=FailureInfo(
                code="invalid_arguments", category="invalid_arguments", rolled_back=False, attempt_id=""
            ),
        )
        await record_attempt(ctx, ref, "noncombat.interaction", bad)
        assert await permit_repair(ctx, hero)
        await record_attempt(ctx, ref, "noncombat.interaction", bad)
        assert not await permit_repair(ctx, hero)

    play(settings, campaign_id, [], check)


def test_creative_cannot_bypass_rule_failure(game):
    from app.tools.resolution.creative import validate_creative_proposal

    settings, campaign_id, hero = game

    async def check(ctx):
        ctx.session.add(MasterTurn(id=ctx.turn_id, campaign_id=campaign_id, status="running"))
        await ctx.session.flush()
        ref = await prepare_action(ctx, hero, [{"verb": "interact"}])
        await record_attempt(
            ctx,
            ref,
            "noncombat.interaction",
            ResolutionResult(
                execution="denied",
                failure=FailureInfo(code="denied", category="rule_denial", rolled_back=True, attempt_id=""),
            ),
        )
        proposal = ResolutionProposal(ref=ref, origin="creative", outcome="success", reason="test")
        assert (await validate_creative_proposal(ctx, proposal)).route == "deny"

    play(settings, campaign_id, [], check)


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
            replay = await adjudicate_action(ctx, AdjudicationArgs(proposal=proposed))
            assert replay["execution"] == "repeated"
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
            await record_attempt(
                ctx,
                ref,
                "noncombat.interaction",
                ResolutionResult(
                    execution="denied",
                    failure=FailureInfo(code="later", category="unsupported", rolled_back=True, attempt_id=""),
                ),
            )
            assert not await eligible_adjudications(ctx)  # a confirmed roll cannot be reopened by a later error
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


@pytest.mark.parametrize(
    ("verb", "route"),
    [("custom", "ordinary"), ("persuade", "ordinary"), ("help", "ordinary"), ("attack", "deny"), ("pick_up", "deny")],
)
def test_creative_admission_covers_free_talk_but_not_combat_or_pickup(game, verb, route):
    # плейтест 19.10: «как тебя зовут?» и «беру бумаги» разбирались как custom, творческий допуск отказывал, и мастер
    # закрывал заявку auto_success без записи; бой и подбор остаются за своими инструментами
    from app.tools.resolution.creative import validate_creative_proposal

    settings, campaign_id, hero = game

    async def check(ctx):
        await execute(ctx, "create_location", {"name": "Tavern", "make_current": True})
        ctx.session.add(MasterTurn(id=ctx.turn_id, campaign_id=campaign_id, status="running"))
        await ctx.session.flush()
        ref = await prepare_action(ctx, hero, [{"verb": verb}])
        proposal = ResolutionProposal(ref=ref, origin="creative", outcome="success", reason="свободная реплика")
        assert (await validate_creative_proposal(ctx, proposal)).route == route

    play(settings, campaign_id, [], check)
