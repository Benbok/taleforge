from app.core.resolution.contracts import Admission
from app.tools import standing
from app.tools.registry import execute
from app.tools.resolution.executor import execute_resolution
from app.tools.resolution.standing import standing_resolution
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


def test_failed_gift_does_not_close_response_and_replay_is_once(game):
    settings, campaign_id, hero = game

    async def check(ctx):
        spawned = await execute(
            ctx, "spawn_entity", {"creature_template_id": "creature.commoner", "name": "Путник", "attitude": "neutral"}
        )
        npc = spawned["result"]["spawned"][0]["id"]
        deed = await execute(
            ctx,
            "record_deed",
            {
                "subject_id": npc,
                "character_ids": [hero],
                "effect": "help",
                "weight": "major",
                "reason": "спасли путника",
            },
        )
        assert deed["ok"]
        await execute(ctx, "advance_time", {"amount": 10, "unit": "day", "reason": "путь"})
        await standing.run_standing(ctx)
        response = ctx.world.scene.state["standing"]["responses"][0]
        assert response["status"] == "ready"
        bad = standing_resolution(
            ctx,
            response["id"],
            [
                {"kind": "gift", "args": {"character_id": hero, "item_template_id": "item.missing", "reason": "дар"}},
            ],
            "подарил предмет",
        )
        result = await execute_resolution(ctx, bad, Admission("ordinary", "standing.response"))
        assert result.execution == "denied"
        assert ctx.world.scene.state["standing"]["responses"][0]["status"] == "ready"
        good = standing_resolution(
            ctx,
            response["id"],
            [
                {"kind": "gift", "args": {"character_id": hero, "item_template_id": "item.dagger", "reason": "дар"}},
            ],
            "подарил кинжал",
        )
        result = await execute_resolution(ctx, good, Admission("ordinary", "standing.response"))
        assert result.execution == "applied"
        assert ctx.world.scene.state["standing"]["responses"][0]["status"] == "done"
        assert (await execute_resolution(ctx, good, Admission("ordinary", "standing.response"))).execution == "repeated"

    play(settings, campaign_id, [], check)


def test_ordinary_and_grouped_deed_count_once(game):
    from sqlalchemy import select

    from app.db.models import Event
    from app.tools.resolution.operations import ResolutionProposal
    from app.tools.resolution.requests import bound_tool_key
    from tests.resolution_helpers import prepare_action

    settings, campaign_id, hero = game

    async def check(ctx):
        spawned = await execute(
            ctx, "spawn_entity", {"creature_template_id": "creature.commoner", "name": "Путник", "attitude": "neutral"}
        )
        npc = spawned["result"]["spawned"][0]["id"]
        ref = await prepare_action(ctx, hero, [{"verb": "interact", "target_id": npc}])
        ctx.required_actions = [ref]
        args = {"subject_id": npc, "character_ids": [hero], "effect": "help", "weight": "major", "reason": "помогли"}
        ordinary = await execute(ctx, "record_deed", args, key=await bound_tool_key(ctx, "record_deed", args, "old"))
        assert ordinary["ok"]
        points_before = ctx.world.scene.state["standing"]["subjects"][npc]["points"]
        proposed = ResolutionProposal(
            ref=ref,
            origin="normal",
            outcome="success",
            reason="test",
            operations=[{"kind": "deed", "args": {**args, "reason": "помогли ещё раз словами"}}],
        )
        assert (
            await execute_resolution(ctx, proposed, Admission("ordinary", "noncombat.interaction"))
        ).execution == "applied"
        rows = (
            await ctx.session.scalars(
                select(Event).where(Event.tool == "record_deed", Event.campaign_id == campaign_id)
            )
        ).all()
        assert len(rows) == 1
        assert ctx.world.scene.state["standing"]["subjects"][npc]["points"] == points_before

    play(settings, campaign_id, [], check)
