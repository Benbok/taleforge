import asyncio

from sqlalchemy import func, select

from app.core.universal.exploration_resolution import resolve_exploration
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Event
from app.rules.dice import FixedDice
from tests.test_exploration_resolution import prepare, run_low
from tests.test_universal_resolution import setup

DC = 12  # the hero has wis 14 (+2): a natural 8 totals 10 and misses by 2, which costs 6 at level 1


async def checked(s, **ctx_fields):
    ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20]), **ctx_fields)
    action = await prepare(s, ctx, "observe", source="mundane", resolution="check")
    return ctx, action.model_copy(update={"difficulty": DC})


def energy(s):
    async def read():
        return int((await s.get(Character, "hero")).resources["energies"]["wis"])

    return read()


def test_stored_roll_without_investment_is_the_same_failure(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await run_low(maker, "20")
        async with maker() as s:
            ctx, action = await checked(s, preroll=(8,))
            result = await resolve_exploration(ctx, action, "m")
            assert not result.success and result.natural == 8 and result.checks[0].invested == 0
        await engine.dispose()

    asyncio.run(run())


def test_investment_buys_the_miss_once_and_pays_the_price(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await run_low(maker, "20")
        async with maker() as s:
            ctx, action = await checked(s, preroll=(8,), invest=True)
            result = await resolve_exploration(ctx, action, "m")
            assert result.success and not result.critical
            assert result.checks[0].invested == 2 and result.checks[0].total == DC
            assert result.cost == 6
            assert await energy(s) == 20 - 6 + 2  # price, plus the two the six game seconds give back
            assert (await resolve_exploration(ctx, action, "m")).status == "repeated"
            assert await energy(s) == 20 - 6 + 2
            assert await s.scalar(select(func.count()).select_from(Event)) == 1
        await engine.dispose()

    asyncio.run(run())


def test_investment_beyond_the_energy_is_denied_and_changes_nothing(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await run_low(maker, "5")
        async with maker() as s:
            ctx, action = await checked(s, preroll=(8,), invest=True)
            result = await resolve_exploration(ctx, action, "m")
            assert result.status == "denied"
            assert await energy(s) == 5
            assert await s.scalar(select(func.count()).select_from(Event)) == 0
        await engine.dispose()

    asyncio.run(run())


def test_investment_on_a_natural_one_is_denied(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await run_low(maker, "20")
        async with maker() as s:
            ctx, action = await checked(s, preroll=(1,), invest=True)
            assert (await resolve_exploration(ctx, action, "m")).status == "denied"
            assert await energy(s) == 20
        await engine.dispose()

    asyncio.run(run())
