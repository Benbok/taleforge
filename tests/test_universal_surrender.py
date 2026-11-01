"""A beaten foe begs instead of striking, as its temper allows, and a blow brings its fight back."""

import asyncio

import pytest

from app.core.universal.combat import run_exchange
from app.core.universal.resolution import ResolutionContext
from app.core.universal.surrender import is_low
from app.db.models import Entity
from app.rules.dice import FixedDice
from tests.test_exploration_resolution import prepare
from tests.test_universal_exchange import enemy
from tests.test_universal_resolution import setup


@pytest.mark.parametrize(
    "hp,hp_max,low", [(5, 20, True), (6, 20, False), (2, 11, True), (3, 11, False), (1, 24, True), (0, 20, False)]
)
def test_low_health_is_a_quarter_and_never_more_than_five(hp, hp_max, low):
    assert is_low(hp, hp_max) is low


async def beaten(s, temper):
    foe = await enemy(s, hp="3")
    foe.state = {**foe.state, "temper": temper}
    await s.flush()
    return foe


def play(tmp_path, temper, rolls):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await beaten(s, temper)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice(rolls))
            action = await prepare(s, ctx, "guard", source="mundane")  # a deed that provokes a reply
            results = await run_exchange(ctx, action, request_key="m")
            foe = await s.get(Entity, "foe", populate_existing=True)
            return results, foe.state, [c.kind for c in results[0].changes]
        await engine.dispose()

    return asyncio.run(run())


def test_a_coward_beaten_low_gives_up_by_the_die_and_does_not_strike(tmp_path):
    results, state, kinds = play(tmp_path, "cowardly", [10])  # the die of the plea; no blow is rolled
    assert len(results) == 1 and state.get("yielded") and "plea" in kinds


def test_a_brave_foe_with_a_high_die_keeps_fighting(tmp_path):
    results, state, kinds = play(tmp_path, "brave", [15, 15, 3])  # a plea die too high, then the foe strikes
    assert len(results) == 2 and not state.get("yielded") and "plea" not in kinds


def test_a_fanatic_never_yields(tmp_path):
    results, state, kinds = play(tmp_path, "fanatic", [15, 3])  # a fanatic is not even asked
    assert len(results) == 2 and not state.get("yielded")
