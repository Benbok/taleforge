import asyncio

from app.core.universal.clock import complete_step
from app.core.universal.profiles import load_actor
from app.db.models import Character, Scene
from app.rules.universal.mechanics import energy_regen
from tests.test_universal_resolution import setup


def test_regeneration_is_an_eighth_of_the_pool_and_never_less_than_one():
    assert [energy_regen(m) for m in (25, 24, 18, 17, 6, 36, 42)] == [2, 2, 2, 1, 1, 3, 4]
    assert energy_regen(1) == 1


async def drained(maker, **energies):
    async with maker() as s:
        hero = await s.get(Character, "hero")
        hero.resources = {**hero.resources, "energies": {**hero.resources["energies"], **energies}}
        await s.commit()


async def energy(s, key="wis"):
    return (await load_actor(s, "c", "hero"))[1].energies[key]


def test_every_pool_comes_back_by_its_own_rate_each_step_and_stops_at_the_pool(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            sheet, _ = await load_actor(s, "c", "hero")
            from app.rules.universal.mechanics import derive, starting_defense_bonuses

            top = derive(sheet, starting_defense_bonuses(sheet)).energy_max
        await drained(maker, wis=str(top["wis"] - 9), str=str(top["str"] - 1))
        async with maker() as s:
            await complete_step(s, "c", "a", 6)
            assert await energy(s) == top["wis"] - 9 + energy_regen(top["wis"])
            assert await energy(s, "str") == top["str"]  # a nearly full pool is capped, not exceeded
            for index in range(10):
                await complete_step(s, "c", f"more{index}", 6)
            assert await energy(s) == top["wis"]
            await s.commit()
        await engine.dispose()

    asyncio.run(run())


def test_a_long_action_restores_for_every_six_seconds_and_a_replayed_step_restores_once(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await drained(maker, wis="1")
        async with maker() as s:
            _, before = await load_actor(s, "c", "hero")
            await complete_step(s, "c", "long", 12)  # two six-second units
            two = await energy(s)
            assert two - 1 == 2 * energy_regen(await top(s, "wis"))
            await complete_step(s, "c", "long", 12)  # the same saved step
            assert await energy(s) == two
            await complete_step(s, "c", "none", 0)  # no time passes, nothing comes back
            assert await energy(s) == two
            assert before.hp == (await load_actor(s, "c", "hero"))[1].hp  # health is not an energy
        await engine.dispose()

    asyncio.run(run())


async def top(s, key):
    from app.rules.universal.mechanics import derive, starting_defense_bonuses

    sheet, _ = await load_actor(s, "c", "hero")
    return derive(sheet, starting_defense_bonuses(sheet)).energy_max[key]


def test_nothing_comes_back_in_combat(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await drained(maker, wis="1")
        async with maker() as s:
            s.add(Scene(campaign_id="c", mode="combat"))
            await s.flush()
            await complete_step(s, "c", "fight", 6)
            assert await energy(s) == 1
            (await s.get(Scene, "c")).mode = "free"
            await complete_step(s, "c", "calm", 6)
            assert await energy(s) > 1
        await engine.dispose()

    asyncio.run(run())
