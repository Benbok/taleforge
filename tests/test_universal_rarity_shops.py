"""Rarer things come harder: less often, by a harder check, at a higher price; a merchant sells what the server
stocked; the same person keeps one name; a beaten foe leaves a purse."""

import asyncio
from collections import Counter
from types import SimpleNamespace

import pytest

from app.core.universal.exploration_resolution import resolve_exploration
from app.core.universal.inventory import owned_items
from app.core.universal.loot import LootSlot, loot_profile, loot_slots, loot_state, shop_slots
from app.core.universal.purse import START_COINS, coins_of, foe_purse
from app.core.universal.resolution import ResolutionContext
from app.core.universal.world_generation import find_known_person
from app.db.models import Character, Entity
from app.rules.dice import FixedDice
from app.rules.universal.failures import ActionValidationError
from app.rules.universal.items import PRICE, TAKE_DIFFICULTY, ItemProfile
from app.rules.universal.profiles import CheckNarration
from tests.test_universal_loot import loot_action
from tests.test_universal_resolution import setup

OUTCOMES = CheckNarration(
    success="Вышло.", failure="Не вышло.", critical_success="Блестяще.", critical_failure="Плохо."
)


def campaign(difficulty="normal"):
    return SimpleNamespace(id="c", difficulty=difficulty, settings={})


def test_rarity_is_rarer_the_higher_it_is():
    counts = Counter(slot.rarity for i in range(3000) for slot in loot_slots(campaign("easy"), str(i)))
    assert counts["common"] > counts["rare"] > counts["unique"] > counts["epic"] > 0
    stock = Counter(slot.rarity for i in range(3000) for slot in shop_slots(campaign(), str(i)))
    assert stock["common"] > stock["rare"] > stock["unique"] >= stock["epic"]


def test_the_author_can_set_how_often_a_place_has_a_stall():
    market = SimpleNamespace(id="c", difficulty="normal", settings={"shop_chance": 100})
    closed = SimpleNamespace(id="c", difficulty="normal", settings={"shop_chance": 0})
    assert all(shop_slots(market, str(i)) for i in range(40)) and not any(shop_slots(closed, str(i)) for i in range(40))


def test_a_stall_shows_every_kind_of_goods():
    market = SimpleNamespace(id="c", difficulty="normal", settings={"shop_chance": 100})
    assert all({s.kind for s in shop_slots(market, str(i))} == {"weapon", "armor", "consumable"} for i in range(30))


@pytest.mark.parametrize("rarity", ["common", "rare", "unique", "epic"])
@pytest.mark.parametrize("kind", ["weapon", "armor", "consumable"])
def test_every_rarity_makes_a_lawful_item_that_grows_with_it(kind, rarity):
    profile = loot_profile(LootSlot("loot_1", kind, rarity), "Находка", "Описание")
    assert ItemProfile.model_validate(profile.model_dump()) == profile and profile.status == rarity
    plain = loot_profile(LootSlot("loot_1", kind, "common"), "Находка", "Описание")
    if rarity != "common":
        better = (
            profile.attack_bonus + profile.damage_bonus > 0
            or profile.defense_bonus > plain.defense_bonus
            or profile.restore_amount > plain.restore_amount
        )
        assert better


def test_difficulty_and_price_climb_with_rarity():
    assert list(TAKE_DIFFICULTY.values()) == sorted(TAKE_DIFFICULTY.values()) and TAKE_DIFFICULTY["common"] == 0
    assert list(PRICE.values()) == sorted(PRICE.values())
    rare = loot_profile(LootSlot("loot_1", "weapon", "rare"), "Клинок", "")
    assert loot_state(LootSlot("loot_1", "weapon", "rare"), rare)["take_difficulty"] == TAKE_DIFFICULTY["rare"]
    assert loot_state(LootSlot("shop_1", "weapon", "rare"), rare, seller_id="m")["price"] == PRICE["rare"]


async def place(s, slot, *, seller=None, ident="find"):
    if await s.get(Entity, "hall") is None:
        s.add(Entity(id="hall", campaign_id="c", kind="location", name="Зал"))
        await s.flush()
        (await s.get(Character, "hero")).location_id = "hall"
    profile = loot_profile(slot, "Находка", "Вещь.", "dex")
    s.add(
        Entity(
            id=ident,
            campaign_id="c",
            location_id="hall",
            kind="object",
            name=profile.name,
            description=profile.description,
            state=loot_state(slot, profile, seller_id=seller),
        )
    )
    await s.flush()


def take_by_check(s, ctx, difficulty, mid):
    return loot_action(
        s,
        ctx,
        [dict(kind="take", object_id="find")],
        resolution="check",
        difficulty=difficulty,
        check_outcomes=OUTCOMES,
        mid=mid,
    )


def test_a_rare_find_is_taken_only_by_a_check_of_its_difficulty(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await place(s, LootSlot("loot_1", "weapon", "rare"))
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([18]))
            with pytest.raises(ValueError):  # no check at all
                await loot_action(s, ctx, [dict(kind="take", object_id="find")])
            with pytest.raises(ValueError):  # a check that is too easy for it
                await take_by_check(s, ctx, 8, "easy")
            ok = await take_by_check(s, ctx, 12, "hard")
            result = await resolve_exploration(ctx, ok, "hard")
            assert result.success and len(await owned_items(s, "c", "hero")) == 1
        await engine.dispose()

    asyncio.run(run())


def test_a_failed_check_leaves_the_rare_find_where_it_lies(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await place(s, LootSlot("loot_1", "weapon", "rare"))
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([2]))
            action = await take_by_check(s, ctx, 12, "take")
            result = await resolve_exploration(ctx, action, "take")
            assert not result.success and (await s.get(Entity, "find")).location_id == "hall"
        await engine.dispose()

    asyncio.run(run())


async def stall(s, rarity="rare"):
    s.add(Entity(id="seller", campaign_id="c", kind="creature", name="Торговец", state={"hostile": False}))
    await s.flush()
    await place(s, LootSlot("shop_1", "weapon", rarity), seller="seller")
    (await s.get(Entity, "seller")).location_id = "hall"


def test_buying_takes_the_price_in_coins_and_gives_the_item(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await stall(s)
            hero = await s.get(Character, "hero")
            assert coins_of(hero) == START_COINS
            hero.resources = {**hero.resources, "coins": "100"}
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await loot_action(s, ctx, [dict(kind="take", object_id="find")])  # a purchase is no check
            result = await resolve_exploration(ctx, action, "take")
            assert result.success and any("Куплено" in c.description for c in result.changes)
            assert coins_of(await s.get(Character, "hero")) == 100 - PRICE["rare"]
            assert len(await owned_items(s, "c", "hero")) == 1
        await engine.dispose()

    asyncio.run(run())


def test_a_hero_without_the_coins_buys_nothing(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await stall(s, "unique")
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            with pytest.raises(ActionValidationError) as caught:
                await loot_action(s, ctx, [dict(kind="take", object_id="find")])
            assert caught.value.failure.code == "not_enough_coins"
            assert coins_of(await s.get(Character, "hero")) == START_COINS
            assert not await owned_items(s, "c", "hero")
        await engine.dispose()

    asyncio.run(run())


def test_the_same_name_is_the_same_person_met_again(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Entity(id="old", campaign_id="c", kind="creature", name="Кихэй", location_id="gate"))
            s.add(
                Entity(
                    id="foe",
                    campaign_id="c",
                    kind="creature",
                    name="Бродяга",
                    location_id="gate",
                    state={"hostile": True},
                )
            )
            await s.flush()
            assert (await find_known_person(s, "c", "кихэй", "road")).id == "old"
            assert await find_known_person(s, "c", "Конуха", "road") is None
            assert await find_known_person(s, "c", "Бродяга", "road") is None  # an enemy is not met as a friend
            assert await find_known_person(s, "c", "Кихэй", "gate") is None  # already here
        await engine.dispose()

    asyncio.run(run())


def test_a_foes_purse_is_fixed_by_its_strength_and_identity():
    assert foe_purse("weak", "a") == foe_purse("weak", "a")
    assert all(1 <= foe_purse("weak", str(i)) <= 4 and 10 <= foe_purse("strong", str(i)) <= 22 for i in range(50))
