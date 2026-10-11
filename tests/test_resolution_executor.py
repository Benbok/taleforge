import pytest
from pydantic import ValidationError

from app.core.resolution.contracts import ActionRef, Admission
from app.db.models import MasterTurn
from app.tools.resolution.executor import execute_resolution
from app.tools.resolution.operations import ResolutionProposal
from tests.resolution_helpers import prepare_action
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


def proposal(campaign_id, hero, operations):
    return ResolutionProposal(
        ref=ActionRef(campaign_id=campaign_id, source_kind="message", source_id="m", actor_id=hero, part=0),
        origin="normal",
        outcome="partial",
        reason="test",
        operations=operations,
    )


def test_second_operation_failure_rolls_back_first(game):
    settings, campaign_id, hero = game

    async def check(ctx):
        ctx.session.add(MasterTurn(id=ctx.turn_id, campaign_id=campaign_id, status="running"))
        await ctx.session.flush()
        before = ctx.world.scene.game_time
        ref = await prepare_action(ctx, hero, [{"verb": "interact"}])
        proposed = proposal(
            campaign_id,
            hero,
            [
                {"kind": "time", "args": {"amount": 1, "unit": "minute", "reason": "test"}},
                {"kind": "remove_item", "args": {"character_id": hero, "inventory_id": "missing", "reason": "test"}},
            ],
        ).model_copy(update={"ref": ref})
        result = await execute_resolution(
            ctx,
            proposed,
            Admission("ordinary", "supported_action"),
        )
        assert result.execution == "denied"
        assert ctx.world.scene.game_time == before
        assert not ctx.events
        turn = await ctx.session.get(MasterTurn, ctx.turn_id)
        assert turn.trace["resolution_operations"][-1]["result"]["error"]
        assert len(turn.trace["resolution_operations"]) == 2

    play(settings, campaign_id, [], check)


@pytest.mark.parametrize(
    "operation",
    [
        {"kind": "sql", "args": {"query": "delete"}},
        {"kind": "time", "args": {"amount": 1, "unit": "minute", "reason": "test", "sql": "delete"}},
        {
            "kind": "neutral_npc",
            "args": {"creature_template_id": "creature.goblin", "name": "G", "attitude": "hostile"},
        },
    ],
)
def test_arbitrary_tool_or_sql_and_hostile_spawn_rejected(operation):
    with pytest.raises(ValidationError):
        proposal("c", "ch", [operation])


def test_rollback_restores_all_context_channels(game):
    from app.tools.resolution.context import restore_context, snapshot_context

    settings, campaign_id, _ = game

    async def check(ctx):
        ctx.call_key = "outer"
        snapshot = snapshot_context(ctx)
        ctx.changed.add("changed")
        ctx.closed.add("closed")
        ctx.signals.add("replan")
        ctx.carded.add("card")
        ctx.outbox.append({"content": "secret"})
        ctx.audio.append({"effect": "x"})
        ctx.notices.append(("notice", {}, None))
        ctx.call_key = "inner"
        restore_context(ctx, snapshot)
        assert not any([ctx.changed, ctx.closed, ctx.signals, ctx.carded, ctx.outbox, ctx.audio, ctx.notices])
        assert ctx.call_key == "outer"

    play(settings, campaign_id, [], check)


def test_executor_rechecks_combat_source_despite_passed_admission(game):
    settings, campaign_id, hero = game

    async def check(ctx):
        ref = await prepare_action(ctx, hero, [{"verb": "attack"}])
        proposed = proposal(
            campaign_id,
            hero,
            [
                {"kind": "time", "args": {"amount": 1, "unit": "minute", "reason": "test"}},
            ],
        ).model_copy(update={"ref": ref})
        before = ctx.world.scene.game_time
        result = await execute_resolution(ctx, proposed, Admission("ordinary", "claimed"))
        assert result.execution == "denied"
        assert ctx.world.scene.game_time == before

    play(settings, campaign_id, [], check)


def test_supporting_fact_does_not_close_player_action(game):
    from app.tools.registry import execute

    settings, campaign_id, hero = game

    async def check(ctx):
        raw = await execute(
            ctx,
            "learn_fact",
            {"character_ids": [hero], "subject_id": hero, "fact": "Получил предложение, но ещё не ответил"},
        )
        assert raw["ok"]
        assert hero not in ctx.closed

    play(settings, campaign_id, [], check)


def test_consequence_cannot_reveal_fact_to_other_group(game):
    from app.db.models import Character

    settings, campaign_id, hero = game

    async def check(ctx):
        peer = Character(campaign_id=campaign_id, name="Другой герой", status="approved", location_id="other_place")
        ctx.session.add(peer)
        await ctx.session.flush()
        ctx.world.characters[peer.id] = peer
        ctx.world.crew = {hero}
        ref = await prepare_action(ctx, hero, [{"verb": "interact"}])
        proposed = proposal(
            campaign_id,
            hero,
            [{"kind": "fact", "args": {"subject_id": hero, "character_ids": [peer.id], "fact": "Тайна первой группы"}}],
        ).model_copy(update={"ref": ref})
        result = await execute_resolution(ctx, proposed, Admission("ordinary", "claimed"))
        assert result.execution == "denied"
        assert not ctx.events

    play(settings, campaign_id, [], check)


def test_registry_refusal_preserves_focus_and_crew(game):
    from app.tools.registry import execute

    settings, campaign_id, hero = game

    async def check(ctx):
        ctx.world.focus, ctx.world.crew = "place_saved", {hero}
        result = await execute(
            ctx,
            "roll_check",
            {"character_id": hero, "stat": "missing_skill", "difficulty": "dc.easy", "reason": "test"},
        )
        assert not result["ok"]
        assert ctx.world.focus == "place_saved" and ctx.world.crew == {hero}

    play(settings, campaign_id, [], check)
