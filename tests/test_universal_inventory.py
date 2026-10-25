import asyncio

import pytest

from app.core.campaigns import AccessDenied
from app.core.universal.inventory import actor_derived, consume, create_item, ensure_inventory, equip, equipped_items
from app.db.models import Character
from app.rules.universal.items import ItemProfile, item_attack_profile
from tests.test_universal_resolution import setup


def test_status_and_rarity_are_bounded_and_never_doubled():
    for status in ["common", "rare", "unique", "epic"]:
        assert ItemProfile(name="Клинок", kind="weapon", status=status).status == status
    with pytest.raises(ValueError):
        ItemProfile(name="Клинок", kind="weapon", status="legendary")
    with pytest.raises(ValueError):
        ItemProfile(name="Клинок", kind="weapon", attack_bonus=1)
    flat = item_attack_profile(ItemProfile(name="Редкий клинок", kind="weapon", status="rare", attack_bonus=1), "item")
    assert flat.attack_bonus == 1 and flat.rarity == "rare"
    assert flat.damage_bonus == 0  # pure damage_amount disables the rarity multiplier when a flat bonus participates


def test_armor_changes_actual_defense_and_replay_is_safe(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.sheet = {**hero.sheet, "abilities": {**hero.sheet["abilities"], "dex": "14", "wis": "10"}}
            hero.resources = {**hero.resources, "energies": {**hero.resources["energies"], "wis": "20"}}
            await ensure_inventory(s, "c", "hero")
            armor = await create_item(
                s, "c", "hero", ItemProfile(name="Кираса", kind="armor", defense_bonus=3), "armor"
            )
            assert (await actor_derived(s, "c", "hero")).ac == 14
            await equip(s, "c", "hero", armor.id, True, "equip")
            assert (await actor_derived(s, "c", "hero")).ac == 17
            await equip(s, "c", "hero", armor.id, True, "equip")
            assert len(await equipped_items(s, "c", "hero")) == 1
            await equip(s, "c", "hero", armor.id, False, "remove")
            assert (await actor_derived(s, "c", "hero")).ac == 14
            with pytest.raises(AccessDenied):
                await equip(s, "c", "target", armor.id, True, "steal")
        await engine.dispose()

    asyncio.run(run())


def test_consumable_restores_one_pool_once_and_clamps(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "energies": {**hero.resources["energies"], "wis": "20"}}
            potion = await create_item(
                s,
                "c",
                "hero",
                ItemProfile(name="Настой", kind="consumable", restore_pool="wis", restore_amount=10),
                "potion",
            )
            await consume(s, "c", "hero", potion.id, "hero", "drink")
            await consume(s, "c", "hero", potion.id, "hero", "drink")
            assert hero.resources["energies"]["wis"] == "24"
            assert hero.resources["energies"]["cha"] == "25"
            assert potion.state["universal_item"]["quantity"] == "0"
            with pytest.raises(AccessDenied):
                await consume(s, "c", "hero", potion.id, "hero", "drink-again")
        await engine.dispose()

    asyncio.run(run())


def test_starter_materializes_once_and_is_not_added_to_replacement(tmp_path):
    from app.rules.universal.contracts import StartingEquipment
    from tests.test_universal_starting_equipment import EQUIPMENT

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.sheet = {
                **hero.sheet,
                "starting_equipment": StartingEquipment.model_validate(EQUIPMENT).model_dump(mode="json"),
            }
            assert (await actor_derived(s, "c", "hero")).ac == 13
            await ensure_inventory(s, "c", "hero")
            await ensure_inventory(s, "c", "hero")
            assert len(await equipped_items(s, "c", "hero")) == 2
            armor = await create_item(
                s, "c", "hero", ItemProfile(name="Кираса", kind="armor", defense_bonus=3), "armor"
            )
            await equip(s, "c", "hero", armor.id, True, "equip")
            assert (await actor_derived(s, "c", "hero")).ac == 15
            await equip(s, "c", "hero", armor.id, False, "remove")
            assert (await actor_derived(s, "c", "hero")).ac == 12
        await engine.dispose()

    asyncio.run(run())
