import asyncio

import pytest
from sqlalchemy import select

from app.core.resolution.contracts import Admission
from app.db.models import Campaign, Event
from app.db.session import make_sessionmaker
from app.tools.resolution.executor import execute_resolution
from app.tools.resolution.operations import ResolutionProposal
from app.tools.resolution.requests import resolution_receipt
from app.tools.runtime import open_context
from tests.game import QueueDice, run
from tests.resolution_helpers import prepare_action
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


def test_committed_receipt_replays_in_new_session(game):
    settings, campaign_id, hero = game

    async def first(ctx):
        ref = await prepare_action(ctx, hero, [{"verb": "interact"}])
        proposal = ResolutionProposal(
            ref=ref,
            origin="normal",
            outcome="success",
            reason="test",
            operations=[
                {"kind": "time", "args": {"amount": 1, "unit": "minute", "reason": "test"}},
            ],
        )
        result = await execute_resolution(ctx, proposal, Admission("ordinary", "supported_action"))
        assert result.execution == "applied"
        receipt = await resolution_receipt(ctx, ref)
        assert len(receipt.payload["fingerprint"]) == 64
        return proposal, result, ctx.world.scene.game_time

    original, result, clock = play(settings, campaign_id, [], first)

    async def repeat(ctx):
        changed = original.model_copy(update={"outcome": "failure", "operations": []})
        replay = await execute_resolution(ctx, changed, Admission("ordinary", "supported_action"))
        assert replay.execution == "repeated"
        assert replay.game_outcome == "success"
        assert replay.event_ids == result.event_ids
        assert ctx.world.scene.game_time == clock
        assert not ctx.events

    play(settings, campaign_id, [], repeat)


def test_concurrent_same_action_runs_hooks_once(game):
    settings, campaign_id, hero = game
    if not settings.database_url.startswith("postgresql"):
        pytest.skip("real concurrent row-lock test requires PostgreSQL")

    async def prepare(ctx):
        return await prepare_action(ctx, hero, [{"verb": "interact"}])

    ref = play(settings, campaign_id, [], prepare)
    proposal = ResolutionProposal(
        ref=ref,
        origin="normal",
        outcome="success",
        reason="test",
        operations=[
            {"kind": "time", "args": {"amount": 1, "unit": "minute", "reason": "test"}},
        ],
    )

    async def concurrent(session):
        factory = make_sessionmaker(session.bind)

        async def worker():
            async with factory() as other:
                campaign = await other.get(Campaign, campaign_id)
                ctx = await open_context(other, campaign, QueueDice([]), turn_id=None, seat_id=None)
                result = await execute_resolution(ctx, proposal, Admission("ordinary", "supported_action"))
                await other.commit()
                return result.execution

        assert sorted(await asyncio.gather(worker(), worker())) == ["applied", "repeated"]
        receipts = (
            await session.scalars(select(Event).where(Event.campaign_id == campaign_id, Event.tool == "resolve_action"))
        ).all()
        costs = (
            await session.scalars(select(Event).where(Event.campaign_id == campaign_id, Event.tool == "advance_time"))
        ).all()
        assert len(receipts) == len(costs) == 1

    run(settings, concurrent)
