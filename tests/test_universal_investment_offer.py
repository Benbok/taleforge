import asyncio
from types import SimpleNamespace

from app.core.universal.investment import (
    await_decision,
    evaluate_offer,
    make_offer,
    settle_offer,
    submit_decision,
)
from app.core.universal.profiles import load_actor
from app.core.universal.resolution import ResolutionContext
from app.db.models import Campaign, GameSession, Message
from app.rules.dice import FixedDice
from tests.test_exploration_resolution import prepare, run_low
from tests.test_universal_resolution import setup

# hero: wis 14 (+2), level 1, so a natural 8 totals 10; against DC 12 it misses by 2 and costs 6


async def scene(tmp_path, wis="20"):
    engine, maker = await setup(tmp_path)
    await run_low(maker, wis)
    s = maker()
    session = await s.__aenter__()
    ctx = ResolutionContext(session, "c", "u", "seat", "hero", FixedDice([20]))
    action = await prepare(session, ctx, "observe", source="mundane", resolution="check")
    sheet, resources = await load_actor(session, "c", "hero")
    return engine, s, session, action.model_copy(update={"difficulty": 12}), sheet, resources


def test_no_offer_when_investing_cannot_or_should_not_help(tmp_path):
    async def run():
        engine, s, session, action, sheet, resources = await scene(tmp_path)
        assert evaluate_offer(action, sheet, resources, [8]) is not None
        assert evaluate_offer(action, sheet, resources, [15]) is None  # already a success
        assert evaluate_offer(action, sheet, resources, [1]) is None  # a natural one stands
        assert evaluate_offer(action.model_copy(update={"difficulty": 16}), sheet, resources, [8]) is None  # miss of 6
        assert evaluate_offer(action.model_copy(update={"attribute": "con"}), sheet, resources, [8]) is None
        assert evaluate_offer(action.model_copy(update={"resolution": "automatic"}), sheet, resources, [8]) is None
        # the action's own cost comes out of the pool first: 24 - 20 leaves 4, below the price of 6
        assert evaluate_offer(action.model_copy(update={"cost": 20}), sheet, resources, [8]) is None
        await s.__aexit__(None, None, None)
        await engine.dispose()

    asyncio.run(run())


def test_offer_names_the_exact_price(tmp_path):
    async def run():
        engine, s, session, action, sheet, resources = await scene(tmp_path)
        terms = evaluate_offer(action, sheet, resources, [8])
        assert (terms.shortfall, terms.price, terms.attribute, terms.available) == (2, 6, "wis", 20)
        await s.__aexit__(None, None, None)
        await engine.dispose()

    asyncio.run(run())


def test_not_enough_energy_means_no_offer(tmp_path):
    async def run():
        engine, s, session, action, sheet, resources = await scene(tmp_path, wis="5")
        assert evaluate_offer(action, sheet, resources, [8]) is None
        await s.__aexit__(None, None, None)
        await engine.dispose()

    asyncio.run(run())


def test_offer_message_is_created_and_settled_under_the_same_id(tmp_path):
    async def run():
        engine, s, session, action, sheet, resources = await scene(tmp_path)
        session.add(GameSession(id="game", campaign_id="c"))
        (await session.get(Campaign, "c")).last_seq = 1  # the prepared source message already holds seq 1
        await session.flush()
        message = await make_offer(session, "c", "game", None, action, sheet, resources, [8], None, "seat")
        assert message.kind == "investment" and message.data["status"] == "offered"
        assert message.data["price"] == 6 and message.data["seat_id"] == "seat" and message.data["mid"] == "m"
        settled = await settle_offer(session, message.id, "invested")
        assert settled.id == message.id and settled.seq == message.seq and settled.data["status"] == "invested"
        assert (await session.get(Message, message.id)).data["status"] == "invested"
        await s.__aexit__(None, None, None)
        await engine.dispose()

    asyncio.run(run())


def test_decision_registry_first_answer_wins_and_timeout_declines():
    async def run():
        service = SimpleNamespace(investments={})
        waiting = asyncio.create_task(await_decision(service, "c", "m", timeout=1))
        await asyncio.sleep(0)
        assert submit_decision(service, "c", "m", True) is True
        assert submit_decision(service, "c", "m", False) is False
        assert await waiting is True
        assert service.investments == {}
        assert await await_decision(service, "c", "m2", timeout=0.05) is False
        assert submit_decision(service, "c", "m2", True) is False  # the offer is closed
        assert service.investments == {}

    asyncio.run(run())
