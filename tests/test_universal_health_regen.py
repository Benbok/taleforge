import asyncio

import pytest

from app.core.universal.clock import complete_step
from app.db.models import Character
from app.rules.dice import FixedDice
from tests.test_universal_exchange import enemy
from tests.test_universal_resolution import setup
from tests.test_universal_review_regressions import _down


@pytest.mark.parametrize("hp,seconds,want", [(10, 3600, "16"), (21, 3600, "22")])
def test_an_hour_of_rest_heals_without_passing_the_maximum(tmp_path, hp, seconds, want):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "hp": str(hp)}
            await complete_step(s, "c", "rest", seconds, dice=FixedDice([]))
            assert hero.resources["hp"] == want
            await complete_step(s, "c", "rest", seconds, dice=FixedDice([]))
            assert hero.resources["hp"] == want
        await engine.dispose()

    asyncio.run(run())


def test_short_steps_add_up_without_losing_the_remainder(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "hp": "10"}
            for i in range(200):
                await complete_step(s, "c", str(i), 6, dice=FixedDice([]))
                if i in (99, 198, 199):
                    assert hero.resources["hp"] == ("12" if i == 199 else "11")
                    assert hero.resources["hp_regen_carry"] == ("594" if i == 198 else "0")
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("state", ["combat", "zero", "full"])
def test_nothing_comes_back_in_combat_at_zero_or_at_full_health(tmp_path, state):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            if state == "combat":
                await enemy(s)
                hero.resources = {**hero.resources, "hp": "10"}
            elif state == "zero":
                _down(hero, stable_at="0")
            before = hero.resources["hp"]
            await complete_step(s, "c", "rest", 600, dice=FixedDice([]))
            assert hero.resources["hp"] == before
            assert int(hero.resources.get("hp_regen_carry", "0")) == 0
        await engine.dispose()

    asyncio.run(run())
