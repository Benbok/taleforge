"""Item ownership regressions from the October 13 playtest."""

import pytest

from app.core import positions
from app.core.object_policy import concealed
from app.core.world_objects import container_parent
from app.db.models import Campaign, Entity, InventoryItem
from app.tools.master.items import _world_item_state
from app.tools.registry import execute
from app.tools.runtime import open_context
from tests.game import QueueDice, import_base, party, run
from tests.test_world_objects_transfer import ok


def play(settings, cid, fn, dice=()):
    async def go(session):
        ctx = await open_context(
            session, await session.get(Campaign, cid), QueueDice(list(dice)), turn_id="t_playtest_items", seat_id=None
        )
        result = await fn(ctx)
        await session.commit()
        return result

    return run(settings, go)


def setup(client, admin, settings):
    import_base(settings)
    campaign, heads, hero = party(client, admin)
    return campaign["id"], hero["id"], heads[0]


async def coin(ctx, hid):
    await ok(ctx, "create_location", {"name": "Камера", "make_current": True})
    item = await ok(
        ctx,
        "place_item",
        {"item_template_id": "item.dagger", "display_name": "Поцарапанная монета", "reason": "находка"},
    )
    uid = item["entity_id"]
    ctx.world.entities[uid].state = {**ctx.world.entities[uid].state, "world_object": _world_item_state()}
    return uid


def keep_args(hid, **kw):
    return {
        "character_id": hid,
        "name": "Поцарапанная монета",
        "kind": "object",
        "how": "found",
        "reason": "находка",
        **kw,
    }


@pytest.mark.parametrize("where", ["scene", "inventory", "other_room"])
def test_keep_found_rejects_copy_of_existing_campaign_item(client, admin, settings, where):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        uid = await coin(ctx, hid)
        if where == "inventory":
            await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid})
        elif where == "other_room":
            await ok(ctx, "create_location", {"name": "Коридор", "make_current": True})
        before = sum(i.qty for i in ctx.world.inventory[hid])
        result = await execute(ctx, "keep_found_item", keep_args(hid, name="  ПОЦАРАПАННАЯ   МОНЕТА  "))
        assert not result["ok"] and "pick_up_item" in result["error"]
        assert sum(i.qty for i in ctx.world.inventory[hid]) == before

    play(settings, cid, scenario)


def test_keep_found_rejects_existing_ordinary_inventory_stack(client, admin, settings):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        await ok(ctx, "keep_found_item", keep_args(hid))
        result = await execute(ctx, "keep_found_item", keep_args(hid))
        assert not result["ok"] and "pick_up_item" in result["error"]
        assert next(i for i in ctx.world.inventory[hid] if i.display_name == "Поцарапанная монета").qty == 1

    play(settings, cid, scenario)


@pytest.mark.parametrize("how", ["stolen", "pried"])
@pytest.mark.parametrize("check", ["absent", "failed", "other_actor", "old_turn", "save"])
def test_keep_found_requires_successful_current_hero_check(client, admin, settings, how, check):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        if check != "absent":
            actor = hid
            if check == "other_actor":
                spawned = await ok(ctx, "spawn_entity", {"creature_template_id": "creature.commoner", "name": "Другой"})
                actor = spawned["spawned"][0]["id"]
            await ok(
                ctx,
                "roll_check",
                {
                    "character_id": actor,
                    "stat": "str",
                    "kind": "save" if check == "save" else "check",
                    "difficulty": "dc.easy",
                    "reason": "добыть вещь",
                },
            )
            if check == "old_turn":
                ctx.events[-1].turn_id = "t_previous"
        result = await execute(ctx, "keep_found_item", keep_args(hid, how=how))
        assert not result["ok"] and "roll_check" in result["error"]
        assert not any(i.display_name == "Поцарапанная монета" for i in ctx.world.inventory[hid])

    play(settings, cid, scenario, [1 if check == "failed" else 20])


def test_keep_found_can_create_new_pried_part_after_success(client, admin, settings):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        await ok(
            ctx,
            "roll_check",
            {"character_id": hid, "stat": "str", "difficulty": "dc.easy", "reason": "выломать арматуру"},
        )
        await ok(ctx, "keep_found_item", keep_args(hid, name="Арматура", kind="improvised_weapon", how="pried"))
        assert any(i.display_name == "Арматура" for i in ctx.world.inventory[hid])

    play(settings, cid, scenario, [20])


def test_keep_found_rejects_unowned_source_item_even_after_success(client, admin, settings):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        spawned = await ok(ctx, "spawn_entity", {"creature_template_id": "creature.commoner", "name": "Шептун"})
        npc = spawned["spawned"][0]["id"]
        await ok(
            ctx,
            "roll_check",
            {"character_id": hid, "stat": "sleight_of_hand", "difficulty": "dc.easy", "reason": "украсть"},
        )
        result = await execute(ctx, "keep_found_item", keep_args(hid, how="stolen", from_id=npc))
        assert not result["ok"]
        assert not any(i.display_name == "Поцарапанная монета" for i in ctx.world.inventory[hid])

    play(settings, cid, scenario, [20])


def test_take_item_preserves_unique_identity_and_inventory(client, admin, settings):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        uid = await coin(ctx, hid)
        row = await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid})
        result = await execute(
            ctx, "take_item", {"character_id": hid, "inventory_id": row["inventory_id"], "reason": "отдать Шептуну"}
        )
        assert not result["ok"] and "pass_item" in result["error"] and "drop_item" in result["error"]
        assert any(i.world_entity_id == uid for i in ctx.world.inventory[hid])
        assert ctx.world.entities[uid].state["world_object"]["physical"] == "intact"

    play(settings, cid, scenario)


async def give_coin_to_npc(ctx, hid):
    uid = await coin(ctx, hid)
    picked = await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid})
    npc = (
        await ok(ctx, "spawn_entity", {"creature_template_id": "creature.commoner", "name": "Шептун", "zone": "melee"})
    )["spawned"][0]["id"]
    await ok(ctx, "pass_item", {"character_id": hid, "to_entity_id": npc, "inventory_id": picked["inventory_id"]})
    return uid, npc


def test_pass_to_npc_keeps_identity_private_and_can_return(client, admin, settings):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        uid, npc = await give_coin_to_npc(ctx, hid)
        entity = ctx.world.entities[uid]
        assert container_parent(entity) == npc
        assert concealed(entity, ctx.world.entities)
        assert uid not in {e.id for e in ctx.world.in_scene_entities()}
        assert not any(i.world_entity_id == uid for rows in ctx.world.inventory.values() for i in rows)
        await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid, "how": "given"})
        assert container_parent(ctx.world.entities[uid]) is None
        assert next(i for i in ctx.world.inventory[hid] if i.world_entity_id == uid).qty == 1
        return uid

    uid = play(settings, cid, scenario)

    async def persisted(session):
        entity = await session.get(Entity, uid)
        from sqlalchemy import select

        rows = (await session.scalars(select(InventoryItem).where(InventoryItem.world_entity_id == uid))).all()
        return entity.location_id, [(r.character_id, r.qty) for r in rows]

    assert run(settings, persisted) == (None, [(hid, 1)])


@pytest.mark.parametrize("reason", ["found", "failed_theft", "other_room", "too_far", "wall"])
def test_npc_owned_item_cannot_be_taken_without_access(client, admin, settings, reason):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        uid, npc = await give_coin_to_npc(ctx, hid)
        how = "given"
        if reason == "found":
            how = "found"
        elif reason == "failed_theft":
            how = "stolen"
            await ok(
                ctx,
                "roll_check",
                {"character_id": hid, "stat": "sleight_of_hand", "difficulty": "dc.easy", "reason": "украсть"},
            )
        elif reason == "other_room":
            await ok(ctx, "create_location", {"name": "Коридор", "make_current": True})
        elif reason == "too_far":
            # вне боя герой подходит к NPC сам; далеко — только в бою, где подходят своим движением
            positions.set_cell(ctx.world, npc, (8, 0))
            ctx.world.scene.mode = "combat"
            ctx.world.scene.turn_order = [{"id": hid}, {"id": npc}]
        elif reason == "wall":
            positions.set_cell(ctx.world, npc, (1, 1))
            room = ctx.world.entities[ctx.world.home()]
            room.state = {
                **(room.state or {}),
                "sketch": {
                    "shape": "room",
                    "cols": 5,
                    "rows": 3,
                    "party": [0, 1],
                    "walls": [[1, 1], [0, 2]],
                    "features": [],
                    "exits": [],
                },
            }
        result = await execute(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid, "how": how})
        assert not result["ok"], result
        assert container_parent(ctx.world.entities[uid]) == npc
        assert not any(i.world_entity_id == uid for i in ctx.world.inventory[hid])

    play(settings, cid, scenario, [1])


def test_successful_theft_moves_npc_item_instead_of_copying(client, admin, settings):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        uid, npc = await give_coin_to_npc(ctx, hid)
        await ok(
            ctx,
            "roll_check",
            {"character_id": hid, "stat": "sleight_of_hand", "difficulty": "dc.easy", "reason": "украсть монету"},
        )
        await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid, "how": "stolen"})
        assert next(i for i in ctx.world.inventory[hid] if i.world_entity_id == uid).qty == 1
        assert container_parent(ctx.world.entities[uid]) is None

    play(settings, cid, scenario, [20])


@pytest.mark.parametrize("bad", [True, False])
def test_place_item_binds_discovery_to_successful_search_check(client, admin, settings, bad):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        await ok(ctx, "create_location", {"name": "Камера", "make_current": True})
        await ok(
            ctx,
            "roll_check",
            {"character_id": hid, "stat": "investigation", "difficulty": "dc.easy", "reason": "искать отмычку"},
        )
        check_id = ctx.events[-1].id
        before = set(ctx.world.entities)
        result = await execute(
            ctx,
            "place_item",
            {
                "item_template_id": "item.dagger",
                "display_name": "Отмычка",
                "reason": "найдена в щели",
                "discovery_check_event_id": "missing" if bad else check_id,
            },
        )
        if bad:
            assert not result["ok"], result
            assert set(ctx.world.entities) == before
        else:
            assert result["ok"], result
            assert ctx.events[-1].payload["discovery_check_event_id"] == check_id

    play(settings, cid, scenario, [20])


def test_transfer_marks_moved_entity_changed(client, admin, settings):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        uid, npc = await give_coin_to_npc(ctx, hid)
        picked = await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid, "how": "given"})
        ctx.changed.clear()
        await ok(ctx, "pass_item", {"character_id": hid, "to_entity_id": npc, "inventory_id": picked["inventory_id"]})
        assert uid in ctx.changed

    play(settings, cid, scenario)


def test_discovered_secret_item_can_return_from_npc(client, admin, settings):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        uid, _ = await give_coin_to_npc(ctx, hid)
        entity = ctx.world.entities[uid]
        entity.state = {**entity.state, "secret": True}
        await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid, "how": "given"})
        assert any(i.world_entity_id == uid for i in ctx.world.inventory[hid])

    play(settings, cid, scenario)


def test_next_context_lists_only_known_npc_possessions(client, admin, settings):
    cid, hid, _ = setup(client, admin, settings)

    async def prepare(ctx):
        uid, npc = await give_coin_to_npc(ctx, hid)
        secret = Entity(
            campaign_id=cid,
            kind="object",
            template_id="item.dagger",
            name="Скрытая отмычка",
            location_id=ctx.world.home(),
            zone="melee",
            state={
                "item": True,
                "secret": True,
                "qty": 1,
                "world_object": {**_world_item_state(), "container_id": npc},
            },
        )
        ctx.session.add(secret)
        await ctx.session.flush()
        ctx.world.entities[secret.id] = secret
        return uid, npc, secret.id

    uid, npc, secret = play(settings, cid, prepare)

    async def verify(ctx):
        table = ctx.world.scene_table()
        assert uid in table and "Поцарапанная монета" in table and "Шептун" in table
        assert secret not in table and "Скрытая отмычка" not in table
        ids = ctx.world.valid_ids()["scene_items"]
        assert uid in ids and secret not in ids
        await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid, "how": "given"})
        assert any(i.world_entity_id == uid for i in ctx.world.inventory[hid])

    play(settings, cid, verify)


async def far_npc(ctx, hid):
    uid = await coin(ctx, hid)
    picked = await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid})
    npc = (
        await ok(ctx, "spawn_entity", {"creature_template_id": "creature.commoner", "name": "Стражник", "zone": "near"})
    )["spawned"][0]["id"]
    positions.set_cell(ctx.world, hid, (0, 0))
    positions.set_cell(ctx.world, npc, (4, 0))
    return picked["inventory_id"], npc


def test_out_of_combat_hero_walks_up_to_hand_an_item_to_npc(client, admin, settings):
    # плейтест 19.10: «даю ягоду стражнику» — герой в трёх клетках, боя нет; отказ «подойдите вплотную»
    # оставлял заявку невыполненной, а подвинуть героя в этом ходе мастеру было нечем
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        inv, npc = await far_npc(ctx, hid)
        await ok(ctx, "pass_item", {"character_id": hid, "to_entity_id": npc, "inventory_id": inv})
        hero, guard = positions.pos_of(ctx.world, hid), positions.pos_of(ctx.world, npc)
        assert positions.distance(hero, guard) <= 5 and hero.cell != (0, 0)

    play(settings, cid, scenario)


def test_in_combat_handing_an_item_still_needs_own_movement(client, admin, settings):
    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        inv, npc = await far_npc(ctx, hid)
        ctx.world.scene.mode = "combat"
        ctx.world.scene.turn_order = [{"id": hid}, {"id": npc}]
        result = await execute(ctx, "pass_item", {"character_id": hid, "to_entity_id": npc, "inventory_id": inv})
        assert not result["ok"] and "вплотную" in result["error"]
        assert positions.pos_of(ctx.world, hid).cell == (0, 0)

    play(settings, cid, scenario)


def test_out_of_combat_hero_walks_up_to_feed_a_goodberry(client, admin, settings):
    from app.tools.master.items import _add_to_inventory

    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        _inv, npc = await far_npc(ctx, hid)
        berry, _ = await _add_to_inventory(ctx, ctx.world.characters[hid], "item.goodberry", None, 3)
        await ok(ctx, "use_item", {"character_id": hid, "inventory_id": berry, "target_id": npc})
        hero, guard = positions.pos_of(ctx.world, hid), positions.pos_of(ctx.world, npc)
        assert positions.distance(hero, guard) <= 5 and hero.cell != (0, 0)

    play(settings, cid, scenario)


def test_npc_eats_goodberries_the_hero_already_handed_over(client, admin, settings):
    # плейтест 19.10: ягоды отданы стражнику, «съешь оставшиеся» не к чему было привязать
    from app.tools.master.items import _add_to_inventory

    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        _inv, npc = await far_npc(ctx, hid)
        berry, _ = await _add_to_inventory(ctx, ctx.world.characters[hid], "item.goodberry", None, 3)
        given = await ok(ctx, "pass_item", {"character_id": hid, "to_entity_id": npc, "inventory_id": berry, "qty": 3})
        held = given["entity_id"]
        refs = {r.id: r for r in ctx.world.addressable_items(hid)}
        assert refs[held].holder_kind == "npc" and refs[held].holder_id == npc and refs[held].qty == 3
        assert held in ctx.world.valid_ids()["usable_items"]
        first = await ok(ctx, "use_item", {"character_id": hid, "inventory_id": held, "target_id": npc})
        assert first["remaining_qty"] == 2 and first["target"] == ctx.world.entities[npc].name
        assert ctx.world.entities[held].state["qty"] == 2
        await ok(ctx, "use_item", {"character_id": hid, "inventory_id": held, "target_id": npc})
        last = await ok(ctx, "use_item", {"character_id": hid, "inventory_id": held, "target_id": npc})
        assert last["remaining_qty"] == 0
        assert ctx.world.entities[held].state["world_object"]["physical"] == "destroyed"

    play(settings, cid, scenario)


def test_item_facts_list_exact_counts_for_whispers(client, admin, settings):
    from app.tools.master.items import _add_to_inventory

    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        _inv, npc = await far_npc(ctx, hid)
        berry, _ = await _add_to_inventory(ctx, ctx.world.characters[hid], "item.goodberry", None, 5)
        await ok(ctx, "pass_item", {"character_id": hid, "to_entity_id": npc, "inventory_id": berry, "qty": 4})
        facts = ctx.world.item_facts(hid)
        assert "×4 — у " + ctx.world.entities[npc].name in facts and "×1 — у героя" in facts

    play(settings, cid, scenario)


def test_order_to_eat_held_berries_is_parsed_without_the_model(client, admin, settings):
    # плейтест 19.10: «Съешь оставшиеся ягоды» стражнику говорю — парсер дал пустой custom, ягоды остались целы
    from app.agents import intent as intents
    from app.tools.master.items import _add_to_inventory

    cid, hid, _ = setup(client, admin, settings)

    async def scenario(ctx):
        _inv, npc = await far_npc(ctx, hid)
        hero = ctx.world.characters[hid]
        berry, _ = await _add_to_inventory(ctx, hero, "item.goodberry", None, 5)
        given = await ok(ctx, "pass_item", {"character_id": hid, "to_entity_id": npc, "inventory_id": berry, "qty": 4})
        parsed = intents.feed_command("«Съешь оставшиеся ягоды» стражнику говорю", ctx.world, hero)
        (action,) = parsed.intent["actions"]
        assert (action["verb"], action["target_id"], action["instrument_id"]) == ("use_item", npc, given["entity_id"])
        assert intents.routable_tool_call(parsed.intent, ctx.world) == (
            "use_item",
            {"character_id": hid, "inventory_id": given["entity_id"], "target_id": npc},
        )
        # без повелительного глагола или без названия предмета разбор остаётся за моделью
        assert intents.feed_command("Говорю стражнику: хорошая погода", ctx.world, hero) is None
        assert intents.feed_command("Съешь это, стражник", ctx.world, hero) is None

    play(settings, cid, scenario)
