import pytest

from app.db.models import Message
from app.tools.registry import ToolError
from app.tools.resolution.requests import action_key, bind_message_actions, bind_world_action
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


def test_ref_survives_reparse_and_new_turn():
    message = Message(id="m_1", campaign_id="c_1", intent={"actions": [{"verb": "talk"}]}, data={"keep": True})
    first = bind_message_actions(message, "ch_1")
    message.intent = {"actions": [{"verb": "search"}, {"verb": "move"}]}
    message.turn_id = "t_new"
    second = bind_message_actions(message, "ch_1")
    assert first == second
    assert action_key(first[0]) == action_key(second[0])
    assert len(action_key(first[0])) == 64
    assert message.data["keep"] is True


def test_wrong_campaign_or_actor_denied():
    message = Message(id="m", campaign_id="c", intent={"actions": [{"verb": "talk"}]})
    bind_message_actions(message, "ch_1")
    with pytest.raises(ValueError):
        bind_message_actions(message, "ch_2")


def test_missing_parser_does_not_bind_custom():
    message = Message(id="m", campaign_id="c", intent=None)
    assert bind_message_actions(message, "ch") == []


def test_standing_response_ref_is_stable():
    first = bind_world_action("c", "response_1", "ch")
    assert first == bind_world_action("c", "response_1", "ch")
    assert action_key(first) != action_key(bind_world_action("c", "response_2", "ch"))


def test_cancelled_message_denied(game):
    from app.tools.resolution.requests import load_action_context

    settings, campaign_id, hero = game

    async def check(ctx):
        ref = bind_world_action(campaign_id, "deleted", hero).model_copy(update={"source_kind": "message"})
        with pytest.raises(ToolError):
            await load_action_context(ctx, ref)

    play(settings, campaign_id, [], check)


def test_source_actor_and_campaign_checked_in_database(game):
    from app.tools.resolution.requests import load_action_context

    settings, campaign_id, hero = game

    async def check(ctx):
        ch = ctx.world.characters[hero]
        message = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=100,
            content="говорю",
            intent={"actions": [{"verb": "talk"}]},
        )
        ctx.session.add(message)
        await ctx.session.flush()
        ref = bind_message_actions(message, hero)[0]
        loaded = await load_action_context(ctx, ref)
        assert loaded.parsed and loaded.verbs == ("talk",)
        assert loaded.module_data_known  # a non-module campaign has no unloaded book canon
        for replacement in ({"campaign_id": "foreign"}, {"actor_id": "foreign"}):
            with pytest.raises(ToolError):
                await load_action_context(ctx, ref.model_copy(update=replacement))

    play(settings, campaign_id, [], check)


def test_multipart_context_is_local(game):
    from app.core.resolution.policy import admit
    from app.tools.resolution.capabilities import CAPABILITIES
    from app.tools.resolution.requests import load_action_context

    settings, campaign_id, hero = game

    async def check(ctx):
        ch = ctx.world.characters[hero]
        message = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=101,
            content="ищу и колдую",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "search", "target_id": hero},
                    {"verb": "cast", "target_id": hero},
                ],
            },
        )
        ctx.session.add(message)
        await ctx.session.flush()
        refs = bind_message_actions(message, hero)
        assert len(refs) == 2

        search_ctx = await load_action_context(ctx, refs[0])
        assert search_ctx.verbs == ("search",)
        assert search_ctx.target_ids == (hero,)
        assert not search_ctx.combat_related
        admission = admit(search_ctx, CAPABILITIES["noncombat.interaction"], None)
        assert admission.route == "ordinary"

        cast_ctx = await load_action_context(ctx, refs[1])
        assert cast_ctx.verbs == ("cast",)
        assert cast_ctx.target_ids == (hero,)
        assert cast_ctx.combat_related

    play(settings, campaign_id, [], check)


def test_progress_preserves_other_parts_and_legacy_data(game):
    from app.core.resolution.contracts import ActionProgress, ResolutionResult
    from app.tools.resolution.requests import set_action_progress

    settings, campaign_id, hero = game

    async def check(ctx):
        ch = ctx.world.characters[hero]
        message = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=102,
            content="действие 1 и действие 2",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "search", "target_id": "chest_1"},
                    {"verb": "talk", "target_id": "npc_1"},
                ],
            },
        )
        ctx.session.add(message)
        await ctx.session.flush()
        refs = bind_message_actions(message, hero)

        prog0 = ActionProgress(
            status="completed",
            result=ResolutionResult(execution="applied", game_outcome="success", event_ids=["ev_1"]),
        )
        prog1 = ActionProgress(status="denied", reason_code="npc_hostile")

        await set_action_progress(ctx, refs[0], prog0)
        await set_action_progress(ctx, refs[1], prog1)

        data = message.data or {}
        assert "resolution_progress" in data
        assert data["resolution_progress"]["0"]["status"] == "completed"
        assert data["resolution_progress"]["1"]["status"] == "denied"
        assert data["resolution_progress"]["1"]["reason_code"] == "npc_hostile"

        completed = data.get("resolution_completed") or {}
        assert "0" in completed
        assert "1" not in completed

        foreign_ref = refs[0].model_copy(update={"campaign_id": "foreign_campaign"})
        with pytest.raises(ToolError):
            await set_action_progress(ctx, foreign_ref, prog0)

        message.intent = {"actions": [{"verb": "fly"}]}
        rebound = bind_message_actions(message, hero)
        assert rebound == refs
        assert len(message.data["resolution_actions"]) == 2

    play(settings, campaign_id, [], check)


def test_terminal_denial_is_not_success_evidence(game):
    from app.core.resolution.contracts import ActionProgress
    from app.tools.resolution.requests import load_action_context, set_action_progress

    settings, campaign_id, hero = game

    async def check(ctx):
        ch = ctx.world.characters[hero]
        message = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=103,
            content="прыгаю в лаву",
            intent={"confidence": 0.9, "actions": [{"verb": "jump"}]},
        )
        ctx.session.add(message)
        await ctx.session.flush()
        refs = bind_message_actions(message, hero)
        ctx.required_actions = list(refs)
        assert hero not in ctx.closed

        prog = ActionProgress(status="denied", reason_code="too_dangerous")
        await set_action_progress(ctx, refs[0], prog)

        assert hero in ctx.closed

        data = message.data or {}
        completed = data.get("resolution_completed") or {}
        assert "0" not in completed

        context = await load_action_context(ctx, refs[0])
        assert context.completed_parts == ()

    play(settings, campaign_id, [], check)
