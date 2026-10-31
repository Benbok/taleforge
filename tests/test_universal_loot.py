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


async def loot_action(s, ctx, operations, mid="take", **kwargs):
    from app.core.chat import next_seq
    from app.core.universal.interpretation import compile_exploration
    from app.db.models import Message
    from app.rules.universal.exploration import IntentReview, IntentV2

    s.add(
        Message(
            id=mid,
            campaign_id="c",
            seq=await next_seq(s, "c"),
            seat_id=ctx.seat_id,
            author_user_id="u",
            kind="action",
            content="Действую",
        )
    )
    await s.flush()
    intent = IntentV2(source="mundane", resolution="automatic", effects=operations, **kwargs)
    return await compile_exploration(
        ctx, intent, IntentReview(verdict="pass"), dict(source_message_id=mid, source_text="Действую", evidence="")
    )


async def lying_loot(s):
    from app.db.models import Character

    location = Entity(id="hall", campaign_id="c", kind="location", name="Зал")
    s.add(location)
    await s.flush()
    (await s.get(Character, "hero")).location_id = "hall"
    profile = loot_profile(LootSlot("loot_1", "weapon"), "Нож", "Стальной нож.", "dex")
    row = Entity(
        id="find",
        campaign_id="c",
        location_id="hall",
        kind="object",
        name=profile.name,
        description=profile.description,
        state={"loot": profile.model_dump(mode="json")},
    )
    s.add(row)
    await s.flush()
    return row


def test_loot_is_visible_taken_once_and_replayed_without_duplication(tmp_path):
    from app.core.universal.exploration_resolution import resolve_exploration
    from app.core.universal.inventory import owned_items, state_of
    from app.core.universal.objects import visible_objects
    from app.core.universal.resolution import ResolutionContext
    from app.rules.dice import FixedDice

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await lying_loot(s)
            views = await visible_objects(s, "c", "hero")
            assert views == [
                dict(
                    id="find",
                    name="Нож",
                    description="Стальной нож.",
                    location_id="hall",
                    template="loot",
                    loot_kind="weapon",
                )
            ]
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            a = await loot_action(s, ctx, [dict(kind="take", object_id="find")])
            result = await resolve_exploration(ctx, a, "take")
            assert result.success and any(c.kind == "item_taken" for c in result.changes)
            assert (await s.get(Entity, "find")).location_id is None
            assert await visible_objects(s, "c", "hero") == []
            items = await owned_items(s, "c", "hero")
            assert len(items) == 1 and state_of(items[0]).profile.base_dice == "1d4"
            assert (await resolve_exploration(ctx, a, "take")).status == "repeated"
            with pytest.raises(ValueError):
                await loot_action(s, ctx, [dict(kind="take", object_id="find")], mid="again")
            assert len(await owned_items(s, "c", "hero")) == 1
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["place", "give", "fill", "pour", "move"])
def test_loot_cannot_be_used_as_raw_material(tmp_path, kind):
    from app.core.universal.resolution import ResolutionContext
    from app.rules.dice import FixedDice

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await lying_loot(s)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            with pytest.raises(ValueError):
                await loot_action(s, ctx, [dict(kind=kind, object_id="find")])
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("flag", ["remote", "hidden", "secret", "private"])
def test_remote_or_hidden_loot_cannot_be_taken(tmp_path, flag):
    from app.core.universal.objects import visible_objects
    from app.core.universal.resolution import ResolutionContext
    from app.rules.dice import FixedDice

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            row = await lying_loot(s)
            if flag == "remote":
                row.location_id = None
            else:
                row.state = {
                    **row.state,
                    ("visibility" if flag == "private" else flag): ("private" if flag == "private" else True),
                }
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            assert await visible_objects(s, "c", "hero") == []
            with pytest.raises(ValueError):
                await loot_action(s, ctx, [dict(kind="take", object_id="find")])
        await engine.dispose()

    asyncio.run(run())


def test_two_heroes_cannot_take_the_same_find(tmp_path):
    from app.core.universal.exploration_resolution import resolve_exploration
    from app.core.universal.inventory import owned_items
    from app.core.universal.resolution import ResolutionContext
    from app.db.models import Character, Seat
    from app.rules.dice import FixedDice

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await lying_loot(s)
            s.add(Seat(id="second", campaign_id="c", role="player", position=2, user_id="u", occupant_type="human"))
            await s.flush()
            other = await s.get(Character, "target")
            other.seat_id, other.location_id = "second", "hall"
            a = await loot_action(
                s, ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([])), [dict(kind="take", object_id="find")]
            )
            b = await loot_action(
                s,
                ResolutionContext(s, "c", "u", "second", "target", FixedDice([])),
                [dict(kind="take", object_id="find")],
                mid="second-take",
            )
            await s.commit()

        async def take(actor, seat, action):
            async with maker() as s:
                ctx = ResolutionContext(s, "c", "u", seat, actor, FixedDice([]))
                result = await resolve_exploration(ctx, action, action.source_message_id)
                await s.commit()
                return result.status

        results = await asyncio.gather(take("hero", "seat", a), take("target", "second", b))
        assert sorted(results) == ["applied", "denied"]
        async with maker() as s:
            assert len(await owned_items(s, "c", "hero")) + len(await owned_items(s, "c", "target")) == 1
        await engine.dispose()

    asyncio.run(run())
