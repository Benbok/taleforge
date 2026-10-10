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
