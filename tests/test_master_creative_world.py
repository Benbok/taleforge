import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.agents.master.creative import creative_opportunities, validate_creative_proposal
from app.db.models import KnownFact
from app.tools.registry import execute
from app.tools.resolution.executor import execute_resolution
from app.tools.resolution.operations import ResolutionProposal
from tests.game import run
from tests.resolution_helpers import prepare_action
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


def test_direct_autonomous_neutral_spawn_cannot_bypass_missing_module_canon(game):
    from app.db.models import MasterTurn

    settings, campaign_id, _ = game

    async def check(ctx):
        place = (await execute(ctx, "create_location", {"name": "Пустая крипта", "make_current": True}))["result"][
            "location_id"
        ]
        ctx.campaign.settings = {**(ctx.campaign.settings or {}), "module": {"id": "missing"}}
        ctx.session.add(MasterTurn(id=ctx.turn_id, campaign_id=campaign_id, status="running"))
        await ctx.session.flush()
        raw = await execute(
            ctx,
            "spawn_entity",
            {
                "creature_template_id": "creature.commoner",
                "name": "Новый NPC",
                "attitude": "neutral",
                "location_id": place,
            },
        )
        assert not raw["ok"] and raw["failure"]["category"] == "rule_denial"
        assert not any(e.name == "Новый NPC" for e in ctx.world.entities.values())

    play(settings, campaign_id, [], check)


def test_neutral_npc_in_verified_free_place_is_registered(game):
    settings, campaign_id, hero = game

    async def check(ctx):
        raw = await execute(ctx, "create_location", {"name": "Новая улица", "make_current": True})
        place = raw["result"]["location_id"]
        ref = await prepare_action(ctx, hero, [{"verb": "inspect", "target_id": place}])
        proposed = ResolutionProposal(
            ref=ref,
            origin="creative",
            outcome="success",
            reason="знакомство",
            operations=[
                {
                    "kind": "neutral_npc",
                    "args": {"creature_template_id": "creature.commoner", "name": "Путник", "location_id": place},
                }
            ],
        )
        admission = await validate_creative_proposal(ctx, proposed)
        assert admission.route == "ordinary"
        result = await execute_resolution(ctx, proposed, admission)
        assert result.execution == "applied"
        npc = next(e for e in ctx.world.entities.values() if e.name == "Путник")
        assert npc.state["attitude"] == "neutral" and npc.location_id == place

    play(settings, campaign_id, [], check)


def test_story_offer_persists_without_player_acceptance(game):
    settings, campaign_id, hero = game

    async def check(ctx):
        raw = await execute(ctx, "create_location", {"name": "Улица", "make_current": True})
        place = raw["result"]["location_id"]
        ref = await prepare_action(ctx, hero, [{"verb": "interact", "target_id": place}])
        proposed = ResolutionProposal(
            ref=ref,
            origin="creative",
            outcome="success",
            reason="предложение",
            operations=[
                {
                    "kind": "story_hook",
                    "subject_id": place,
                    "character_ids": [hero],
                    "fact": "Помочь путнику найти пропавшую телегу",
                }
            ],
        )
        admission = await validate_creative_proposal(ctx, proposed)
        assert admission.route == "ordinary"
        assert (await execute_resolution(ctx, proposed, admission)).execution == "applied"
        with pytest.raises(ValidationError):
            ResolutionProposal.model_validate(
                {**proposed.model_dump(), "operations": [{**proposed.operations[0].model_dump(), "status": "accepted"}]}
            )

    play(settings, campaign_id, [], check)

    async def saved(session):
        fact = await session.scalar(select(KnownFact).where(KnownFact.character_id == hero))
        assert fact.text.startswith("Предложение (не принято):")

    run(settings, saved)


def test_missing_module_data_is_not_creative_space(game):
    settings, campaign_id, _ = game

    async def check(ctx):
        await execute(ctx, "create_location", {"name": "Пустая крипта", "make_current": True})
        ctx.campaign.settings = {**(ctx.campaign.settings or {}), "module": {"id": "missing"}}
        assert not any(op.kind == "new_neutral" for op in creative_opportunities(ctx))

    play(settings, campaign_id, [], check)
