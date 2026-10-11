import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.resolution.contracts import Admission
from app.db.models import Campaign
from app.db.session import make_sessionmaker
from app.tools.resolution.executor import execute_resolution
from app.tools.resolution.operations import ResolutionProposal
from app.tools.resolution.requests import lock_resolution_source
from app.tools.runtime import open_context
from tests.game import QueueDice, run
from tests.resolution_helpers import prepare_action
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


def test_sqlite_busy_never_grants_fallback_or_runs_consequences(game):
    settings, campaign_id, hero = game
    if not settings.database_url.startswith("sqlite"):
        pytest.skip("SQLite locking behavior")

    async def prepare(ctx):
        return await prepare_action(ctx, hero, [{"verb": "interact"}])

    ref = play(settings, campaign_id, [], prepare)
    proposal = ResolutionProposal(
        ref=ref,
        origin="normal",
        outcome="success",
        reason="test",
        operations=[{"kind": "time", "args": {"amount": 1, "unit": "minute", "reason": "test"}}],
    )

    async def locked(session):
        factory = make_sessionmaker(session.bind)
        async with factory() as first, factory() as second:
            ctx1 = await open_context(
                first, await first.get(Campaign, campaign_id), QueueDice([]), turn_id=None, seat_id=None
            )
            dice = QueueDice([17])
            ctx2 = await open_context(second, await second.get(Campaign, campaign_id), dice, turn_id=None, seat_id=None)
            await second.execute(text("PRAGMA busy_timeout=1"))
            await lock_resolution_source(ctx1, ref)
            with pytest.raises(OperationalError):
                await execute_resolution(ctx2, proposal, Admission("ordinary", "supported_action"))
            assert not ctx2.events and not ctx2.resolution_calls_used and dice.queue == [17]
            await second.rollback()
            await first.rollback()

    run(settings, locked)
