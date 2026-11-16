"""Encounters: the server decides how many foes a scene has and how strong, the model only names and describes."""

import asyncio
from collections import Counter
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.universal.combat import run_exchange
from app.core.universal.combat_actions import initialize_combatant
from app.core.universal.foes import POWER_ABILITIES, foe_slots
from app.core.universal.resolution import ResolutionContext
from app.core.universal.world_generation import publish_scene, reserve_scene
from app.db.models import Campaign, Entity, Message
from app.rules.dice import FixedDice
from app.rules.universal.world import WorldScenePlan
from tests.test_exploration_resolution import prepare
from tests.test_universal_exchange import enemy
from tests.test_universal_resolution import setup


def campaign(difficulty="normal", enabled=True):
    return SimpleNamespace(id="c", difficulty=difficulty, settings={"encounters_enabled": enabled})


def test_foe_slots_are_deterministic_bounded_and_never_at_the_entry():
    c = campaign()
    for i in range(200):
        slots = foe_slots(c, str(i))
        assert slots == foe_slots(c, str(i))
        assert len(slots) <= 4
        assert [s.ref for s in slots] == [f"foe_{n + 1}" for n in range(len(slots))]
        assert all(s.power in {"weak", "normal", "strong"} for s in slots)
        assert foe_slots(c, str(i), entry=True) == []
    assert all(foe_slots(campaign(enabled=False), str(i)) == [] for i in range(50))


def test_a_harder_world_meets_more_and_stronger_foes():
    def mean(difficulty):
        counts = [len(foe_slots(campaign(difficulty), str(i))) for i in range(1500)]
        return sum(counts) / len(counts)

    means = [mean(d) for d in ("easy", "normal", "hard", "deadly")]
    assert means == sorted(means) and means[2] >= 1.8  # on hard nearly every new scene has someone waiting
    assert min(len(foe_slots(campaign("hard"), str(i))) for i in range(1500)) >= 1
    strong = {
        d: Counter(s.power for i in range(1500) for s in foe_slots(campaign(d), str(i))) for d in ("easy", "hard")
    }
    assert strong["easy"]["strong"] == 0 and strong["hard"]["weak"] > strong["hard"]["strong"] > 0  # many weak ones


def test_a_weak_foe_has_fewer_hit_points_than_a_strong_one(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            for ref, power in (("weak_foe", "weak"), ("plain_foe", "normal"), ("strong_foe", "strong")):
                s.add(
                    Entity(id=ref, campaign_id="c", kind="creature", name=ref, state={"hostile": True, "power": power})
                )
            await s.flush()
            hp = {}
            for ref in ("weak_foe", "plain_foe", "strong_foe"):
                await initialize_combatant(s, "c", ref)
                hp[ref] = int((await s.get(Entity, ref)).state["resources"]["hp"])
            assert hp["weak_foe"] < hp["plain_foe"] < hp["strong_foe"]
            assert hp["plain_foe"] == 20 and hp["weak_foe"] <= 12  # the ordinary foe is what it always was
            assert set(POWER_ABILITIES) == {"weak", "normal", "strong"}
        await engine.dispose()

    asyncio.run(run())


def test_a_foe_in_sight_comes_for_a_hero_who_only_looks_and_talks(tmp_path):
    """The pace of a hard world: a foe that stays in view is not a still life, it attacks the second quiet turn."""

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([15, 1, 15, 1]))
            counts = []
            for index in range(3):
                if index:
                    (await s.get(Message, f"m{index - 1}")).seq = -index
                    await s.flush()
                action = await prepare(s, ctx, "wait", source="mundane", mid=f"m{index}")
                counts.append(len(await run_exchange(ctx, action, request_key=f"m{index}")))
                if index == 1:  # the replay of the turn the foe joined is the same turn, not a new reply
                    again = await run_exchange(ctx, action, request_key="m1")
                    assert len(again) == 2
            assert counts == [1, 2, 2]  # looks once unseen, the second time it is on the hero, and it stays on them
        await engine.dispose()

    asyncio.run(run())


async def reserved_foe_scene(s, count):
    c = await s.get(Campaign, "c")
    c.difficulty = "hard"
    loc_id = next(str(i) for i in range(300) if len(foe_slots(c, str(i))) == count)
    s.add(Entity(id=loc_id, campaign_id="c", kind="location", name="Склон", description="Каменный склон."))
    await s.flush()
    return await reserve_scene(s, c, loc_id), foe_slots(c, loc_id)


@pytest.mark.parametrize("given", ["all", "none"])
def test_published_foes_follow_the_slots_and_fill_the_missing_ones(tmp_path, given):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            row, slots = await reserved_foe_scene(s, 2)
            objects = [dict(ref="rock", kind="object", name="Валун")]
            if given == "all":
                objects += [
                    dict(ref=slot.ref, kind="creature", name=f"Тварь {i}", description="Рычит.", hostile=True)
                    for i, slot in enumerate(slots)
                ]
            plan = WorldScenePlan.model_validate(dict(name="Склон", description="Ночь.", objects=objects))
            await publish_scene(s, row, plan)
            foes = [e for e in await s.scalars(select(Entity)) if e.kind == "creature"]
            assert len(foes) == len(slots)
            assert all(e.state["hostile"] for e in foes)
            assert sorted(e.state["power"] for e in foes) == sorted(slot.power for slot in slots)
            if given == "all":
                assert {e.name for e in foes} == {"Тварь 0", "Тварь 1"}
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("effect", ["cannot_act", "cannot_target", "cannot_move"])
def test_a_stunned_or_bound_foe_does_not_strike_back(tmp_path, effect):
    """A foe made unable to act, to choose a target or to move must not reply to a blow. Found in play: a dog bound
    by a vine bit the hero the same turn, within reach."""
    from app.core.universal.effects import start_effect
    from app.db.models import Event
    from app.rules.universal.exploration import EffectIntentV2
    from tests.test_universal_combat_actions import attack

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            s.add(Event(id="stun", campaign_id="c", actor_id="hero", tool="universal_action", payload={}))
            await s.flush()
            await start_effect(s, "c", "hero", "foe", "stun", "stun", EffectIntentV2(kind=effect), 0, 600)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([15, 4, 15, 4]))
            action = await attack(s, ctx, [EffectIntentV2(kind="damage")], targets=["foe"])
            results = await run_exchange(ctx, action, request_key="attack")
            assert len(results) == 1  # the hero's deed alone, no reply
        await engine.dispose()

    asyncio.run(run())
