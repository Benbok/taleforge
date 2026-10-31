import asyncio
from collections import Counter
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.universal.loot import LootSlot, loot_profile, loot_slots
from app.core.universal.world_generation import publish_scene, reserve_scene
from app.db.models import Campaign, Entity
from app.rules.universal.items import ItemProfile
from app.rules.universal.world import WorldScenePlan
from tests.test_universal_resolution import setup


async def reserved_scene(s, count=1):
    c = await s.get(Campaign, "c")
    c.difficulty = "normal"
    loc_id = next(str(i) for i in range(100) if len(loot_slots(c, str(i))) == count)
    location = Entity(id=loc_id, campaign_id="c", kind="location", name="Зал", description="Каменный зал.")
    s.add(location)
    await s.flush()
    return await reserve_scene(s, c, loc_id)


def test_the_scene_context_carries_the_loot_slots(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            row = await reserved_scene(s)
            slots = row.reservation["context"]["loot_slots"]
            assert len(slots) == 1 and slots[0]["ref"] == "loot_1"
            assert slots[0]["kind"] in {"weapon", "armor", "consumable"}
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("count,items", [(1, 1), (1, 2), (1, 0), (0, 2), (2, 2)])
def test_published_loot_is_bounded_filled_and_not_built_twice(tmp_path, count, items):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            row = await reserved_scene(s, count)
            plan = WorldScenePlan.model_validate(
                dict(
                    name="Зал",
                    description="На камнях пыль.",
                    objects=[dict(ref="bench", kind="object", name="Скамья")],
                    items=[
                        dict(ref=f"loot_{i + 1}", name=f"Находка {i + 1}", description="На полу.", attribute="dex")
                        for i in range(items)
                    ],
                )
            )
            first = await publish_scene(s, row, plan)
            rows = [e for e in await s.scalars(select(Entity)) if "loot" in e.state]
            assert len(rows) == count
            for e in rows:
                assert e.kind == "object" and e.location_id == row.target_entity_id
                profile = ItemProfile.model_validate(e.state["loot"])
                assert profile.status == "common"
                if items:
                    assert profile.name.startswith("Находка")
                else:
                    assert profile.name in {"Фляга с настойкой", "Потёртый нож", "Кожаная куртка"}
            assert await publish_scene(s, row, plan) == first
            assert len([e for e in await s.scalars(select(Entity)) if "loot" in e.state]) == count
        await engine.dispose()

    asyncio.run(run())


def campaign(difficulty="normal", enabled=True):
    return SimpleNamespace(id="c", difficulty=difficulty, settings={"loot_enabled": enabled})


def test_slots_are_deterministic_and_bounded():
    c = campaign()
    for i in range(200):
        slots = loot_slots(c, str(i))
        assert slots == loot_slots(c, str(i))
        assert len(slots) <= 2
        assert [s.ref for s in slots] == ["loot_1", "loot_2"][: len(slots)]
        assert all(s.kind in {"consumable", "weapon", "armor"} for s in slots)


def test_the_table_is_followed():
    for difficulty, shares in [("easy", [0.2, 0.5, 0.3]), ("normal", [0.3, 0.6, 0.1]), ("hard", [0.6, 0.4, 0])]:
        counts = Counter(len(loot_slots(campaign(difficulty), str(i))) for i in range(2000))
        for n, share in enumerate(shares):
            assert abs(counts[n] / 2000 - share) < 0.08
    for i in range(200):
        assert loot_slots(campaign("deadly"), str(i)) == []
        assert loot_slots(campaign(enabled=False), str(i)) == []


@pytest.mark.parametrize("kind", ["weapon", "armor", "consumable"])
def test_profile_numbers_come_from_the_server(kind):
    profile = loot_profile(LootSlot("loot_1", kind), "Находка", "Описание")
    assert ItemProfile.model_validate(profile.model_dump()) == profile
    assert profile.status == "common"
    assert profile.attack_bonus == profile.damage_bonus == 0
    if kind == "weapon":
        assert profile.base_dice == "1d6"
        assert loot_profile(LootSlot("loot_1", kind), "Нож", "", "dex").base_dice == "1d4"
        with pytest.raises(ValueError):
            loot_profile(LootSlot("loot_1", kind), "Нож", "", "wis")
    elif kind == "armor":
        assert profile.defense_bonus == 1
    else:
        assert profile.restore_pool == "hp" and profile.restore_amount == 6
