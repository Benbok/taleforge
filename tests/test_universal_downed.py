"""A fallen hero is out of the game, not out of the world: the party can lift them, foes strike them only when nobody
stands, and a hero alone has a single throw."""

import asyncio

from app.core.universal.clock import complete_step
from app.core.universal.vitality import downed_reason, enter_zero_hp, harm_unconscious, public_vitality
from app.db.models import Character
from app.rules.dice import FixedDice
from tests.test_universal_resolution import setup
from tests.test_universal_vitality import join_ally


async def fall(s, sequence=0):
    hero = await s.get(Character, "hero")
    hero.resources = {**hero.resources, "hp": "0"}
    await enter_zero_hp(s, "c", "hero", "injury", sequence)
    return hero


def test_a_lone_hero_rises_on_one_good_throw(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await fall(s)
            await complete_step(s, "c", "first", 6, dice=FixedDice([10]))
            assert public_vitality(hero) == "conscious" and hero.resources["hp"] == "1"
        await engine.dispose()

    asyncio.run(run())


def test_a_lone_hero_dies_on_one_bad_throw(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await fall(s)
            await complete_step(s, "c", "first", 6, dice=FixedDice([9]))
            assert public_vitality(hero) == "dead"
        await engine.dispose()

    asyncio.run(run())


def test_a_blow_on_a_lone_hero_is_death_but_a_party_hero_has_saves_left(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await fall(s)
            await harm_unconscious(s, "c", "hero", "blow", 1)
            assert public_vitality(hero) == "dead"
        async with maker() as s:
            await join_ally(s)
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "hp": "0", "vitality": {}}
            await enter_zero_hp(s, "c", "hero", "injury", 0)
            await harm_unconscious(s, "c", "hero", "blow", 1)
            assert public_vitality(hero) == "unconscious" and hero.resources["vitality"]["failures"] == "1"
        await engine.dispose()

    asyncio.run(run())


def test_a_fallen_hero_cannot_speak_or_act(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await fall(s)
            assert downed_reason(hero)
            hero.resources = {**hero.resources, "hp": "5"}
            assert downed_reason(hero) is None
        await engine.dispose()

    asyncio.run(run())


def test_foes_strike_the_fallen_only_when_nobody_stands(tmp_path):
    from types import SimpleNamespace

    from app.core.universal.combat import eligible_enemies
    from app.core.universal.resolution import ResolutionContext
    from tests.test_exploration_resolution import prepare
    from tests.test_universal_exchange import enemy

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await join_ally(s)
            await enemy(s)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await prepare(s, ctx, "guard", source="mundane")
            exchange = SimpleNamespace(
                actor_id="hero", proposal=action.model_dump(mode="json"), id="x", hero_event_id=None
            )
            await fall(s)
            assert (await eligible_enemies(ctx, exchange))[0]["target_ids"] == ["target"]  # the ally still stands
            ally = await s.get(Character, "target")
            ally.resources = {**ally.resources, "hp": "0"}
            await enter_zero_hp(s, "c", "target", "injury", 0)
            targets = (await eligible_enemies(ctx, exchange))[0]["target_ids"]
            assert sorted(targets) == ["hero", "target"]  # nobody stands: the fallen are all that is left
        await engine.dispose()

    asyncio.run(run())
