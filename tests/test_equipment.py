"""Rules shared by the player equipment endpoint and the master equip_item tool."""

from tests.test_tools import call, game, play  # noqa: F401


def test_two_handed_weapon_displaces_held_weapon_and_shield(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        current = {item.item_template_id: item for item in ctx.world.inventory[hero]}
        assert current["item.shield"].equipped
        arm = await call(
            ctx, "equip_item", {"character_id": hero, "inventory_id": current["item.longsword"].id, "equipped": True}
        )
        assert arm["ok"], arm
        greatsword = await call(
            ctx, "give_item", {"character_id": hero, "item_template_id": "item.greatsword", "reason": "test"}
        )
        assert greatsword["ok"], greatsword
        equipped = await call(
            ctx,
            "equip_item",
            {"character_id": hero, "inventory_id": greatsword["result"]["inventory_id"], "equipped": True},
        )
        assert equipped["ok"], equipped
        after = {item.item_template_id: item for item in ctx.world.inventory[hero]}
        return after

    after = play(settings, cid, [], fn)
    assert after["item.greatsword"].equipped
    assert not after["item.longsword"].equipped
    assert not after["item.shield"].equipped


def test_switching_weapon_in_hero_turn_uses_free_interaction_then_action(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        await call(ctx, "create_location", {"name": "Площадь", "make_current": True})
        gob = (await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"}))[
            "result"
        ]["spawned"][0]["id"]
        inv = {item.item_template_id: item for item in ctx.world.inventory[hero]}
        assert (
            await call(
                ctx, "equip_item", {"character_id": hero, "inventory_id": inv["item.shield"].id, "equipped": False}
            )
        )["ok"]
        assert (
            await call(
                ctx, "equip_item", {"character_id": hero, "inventory_id": inv["item.longsword"].id, "equipped": True}
            )
        )["ok"]
        await call(ctx, "set_scene_mode", {"mode": "combat", "participants": [hero, gob]})
        ctx.world.scene.state = {
            **ctx.world.scene.state,
            "turn": [x["id"] for x in ctx.world.scene.turn_order].index(hero),
        }
        bow = await call(ctx, "give_item", {"character_id": hero, "item_template_id": "item.longbow", "reason": "test"})
        switch = await call(
            ctx, "equip_item", {"character_id": hero, "inventory_id": bow["result"]["inventory_id"], "equipped": True}
        )
        return switch, ctx.world.scene.state.get("spent", {}).get(hero)

    switch, spent = play(settings, cid, [], fn)
    assert switch["ok"], f"switch={switch!r} spent={spent!r}"
    assert spent["interaction_used"] is True and spent["actions"] == 1


def test_equipment_is_rejected_outside_hero_turn_and_armor_is_rejected_in_combat(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        await call(ctx, "create_location", {"name": "Площадь", "make_current": True})
        gob = (await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"}))[
            "result"
        ]["spawned"][0]["id"]
        await call(ctx, "set_scene_mode", {"mode": "combat", "participants": [hero, gob]})
        ctx.world.scene.state = {
            **ctx.world.scene.state,
            "turn": [x["id"] for x in ctx.world.scene.turn_order].index(gob),
        }
        inv = {item.item_template_id: item for item in ctx.world.inventory[hero]}
        outside = await call(
            ctx, "equip_item", {"character_id": hero, "inventory_id": inv["item.longsword"].id, "equipped": True}
        )
        ctx.world.scene.state = {
            **ctx.world.scene.state,
            "turn": [x["id"] for x in ctx.world.scene.turn_order].index(hero),
        }
        armor = await call(
            ctx, "equip_item", {"character_id": hero, "inventory_id": inv["item.chain_mail"].id, "equipped": False}
        )
        return outside, armor

    outside, armor = play(settings, cid, [], fn)
    assert not outside["ok"] and "только в свой ход" in outside["error"]
    assert not armor["ok"] and "доспех в бою" in armor["error"]


def test_composite_switch_is_atomic_when_no_action_remains(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        await call(ctx, "create_location", {"name": "Площадь", "make_current": True})
        gob = (await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"}))[
            "result"
        ]["spawned"][0]["id"]
        inv = {item.item_template_id: item for item in ctx.world.inventory[hero]}
        await call(ctx, "equip_item", {"character_id": hero, "inventory_id": inv["item.shield"].id, "equipped": False})
        await call(
            ctx, "equip_item", {"character_id": hero, "inventory_id": inv["item.longsword"].id, "equipped": True}
        )
        await call(ctx, "set_scene_mode", {"mode": "combat", "participants": [hero, gob]})
        ctx.world.scene.state = {
            **ctx.world.scene.state,
            "turn": [x["id"] for x in ctx.world.scene.turn_order].index(hero),
        }
        bow = await call(ctx, "give_item", {"character_id": hero, "item_template_id": "item.longbow", "reason": "test"})
        await call(ctx, "take_action", {"character_id": hero, "action": "dash"})
        before = {
            "equipped": {item.id: item.equipped for item in ctx.world.inventory[hero]},
            "spent": dict(ctx.world.scene.state.get("spent", {}).get(hero, {})),
        }
        result = await call(
            ctx, "equip_item", {"character_id": hero, "inventory_id": bow["result"]["inventory_id"], "equipped": True}
        )
        after = {
            "equipped": {item.id: item.equipped for item in ctx.world.inventory[hero]},
            "spent": dict(ctx.world.scene.state.get("spent", {}).get(hero, {})),
        }
        return result, before, after

    result, before, after = play(settings, cid, [], fn)
    assert not result["ok"] and "действие этого хода уже потрачено" in result["error"]
    assert after == before
