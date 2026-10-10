from app.agents.master.creative import creative_context, creative_note
from app.tools.registry import execute
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


def test_creative_context_preserves_failed_roll_and_world(game):
    settings, campaign_id, hero = game

    async def check(ctx):
        raw = await execute(
            ctx,
            "roll_check",
            {"character_id": hero, "stat": "persuasion", "difficulty": "dc.hard", "reason": "необычная просьба"},
        )
        assert raw["ok"] and not raw["result"]["success"]
        event_ids = [event.id for event in ctx.events]
        clock = ctx.world.scene.game_time
        context = creative_context(ctx, None)
        assert context["results"][0]["success"] is False
        assert context["mode"] == "noncombat"
        assert creative_note(context)
        assert ctx.world.scene.game_time == clock
        assert [event.id for event in ctx.events] == event_ids

    play(settings, campaign_id, [1], check)


def test_combat_creativity_is_presentation_only(game):
    settings, campaign_id, _ = game

    async def check(ctx):
        ctx.world.scene.mode = "combat"
        context = creative_context(ctx, None)
        assert context["mode"] == "combat"
        assert context["allowed"] == ["presentation"]
        assert not ctx.events

    play(settings, campaign_id, [], check)
