import asyncio

from app.core.universal.clock import complete_step
from app.core.universal.vitality import enter_zero_hp, public_vitality
from app.db.models import Character
from app.rules.dice import FixedDice
from tests.test_universal_resolution import setup


def test_new_zero_hp_waits_until_next_step_and_twenty_rescues_once(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "hp": "0"}
            await enter_zero_hp(s, "c", "hero", "injury", 1)
            await complete_step(s, "c", "first", 6, dice=FixedDice([]))
            assert hero.resources["vitality"]["failures"] == "0"
            await complete_step(s, "c", "second", 6, dice=FixedDice([20]))
            assert hero.resources["hp"] == "1" and public_vitality(hero) == "conscious"
            await complete_step(s, "c", "second", 6, dice=FixedDice([]))
            assert hero.resources["hp"] == "1"
        await engine.dispose()

    asyncio.run(run())


def test_two_natural_ones_die_and_public_state_excludes_counters(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "hp": "0"}
            await enter_zero_hp(s, "c", "hero", "injury", 0)
            first = await complete_step(s, "c", "first", 6, dice=FixedDice([1]))
            assert hero.resources["vitality"]["failures"] == "2"
            assert all(c.get("private") for c in first.changes if c["kind"] == "rescue_roll")
            await complete_step(s, "c", "second", 6, dice=FixedDice([1]))
            assert public_vitality(hero) == "dead"
            assert public_vitality(hero) not in {"2", "4"}
        await engine.dispose()

    asyncio.run(run())


def test_world_events_follow_knockout_until_actionable_without_offline_timer(tmp_path):
    from app.core.universal.combat import run_exchange
    from app.core.universal.resolution import ResolutionContext
    from tests.test_exploration_resolution import prepare
    from tests.test_universal_exchange import enemy

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "hp": "2"}
            await enemy(s)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20, 6, 6, 20]))
            action = await prepare(s, ctx, "wait", source="mundane")
            result = await run_exchange(ctx, action, request_key="m")
            assert len(result) == 2 and hero.resources["hp"] == "1"
            assert public_vitality(hero) == "conscious"
            assert result[1].rolls == [20, 6, 6]
            from app.core.universal.clock import clock_view

            assert (await clock_view(s, "c"))["step_index"] == "2"
        await engine.dispose()

    asyncio.run(run())


def test_healing_clears_living_rescue_state_but_does_not_revive_dead(tmp_path):
    import pytest

    from app.core.campaigns import AccessDenied
    from app.core.universal.inventory import consume, create_item
    from app.rules.universal.items import ItemProfile

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "hp": "0"}
            await enter_zero_hp(s, "c", "hero", "injury", 0)
            potion = await create_item(
                s, "c", "hero", ItemProfile(name="Лекарство", kind="consumable", restore_pool="hp"), "potion"
            )
            await consume(s, "c", "hero", potion.id, "hero", "heal")
            assert public_vitality(hero) == "conscious" and hero.resources["hp"] == "6"
            hero.resources = {**hero.resources, "hp": "0", "vitality": {"state": "dead"}}
            other = await create_item(
                s, "c", "hero", ItemProfile(name="Лекарство", kind="consumable", restore_pool="hp"), "potion2"
            )
            with pytest.raises(AccessDenied):
                await consume(s, "c", "hero", other.id, "hero", "revive")
            assert other.state["universal_item"]["quantity"] == "1"
        await engine.dispose()

    asyncio.run(run())
