"""Regressions for persistent unique objects and explicit nested containers."""

from app.db.models import Campaign, Entity, InventoryItem
from app.tools.master.items import _world_item_state
from app.tools.registry import execute
from app.tools.runtime import flush_outbox, open_context
from tests.game import QueueDice, import_base, party, run
from tests.test_map import _map


def play(settings, cid, fn):
    async def go(session):
        campaign = await session.get(Campaign, cid)
        ctx = await open_context(session, campaign, QueueDice([]), turn_id="t_world_objects", seat_id=None)
        result = await fn(ctx)
        await flush_outbox(session, ctx)
        await session.commit()
        return result

    return run(settings, go)


async def ok(ctx, name, args):
    result = await execute(ctx, name, args)
    assert result["ok"], result
    return result["result"]


def test_unique_scene_item_keeps_entity_identity_across_inventory(client, admin, settings):
    import_base(settings)
    campaign, (player,), hero = party(client, admin)
    cid, hid = campaign["id"], hero["id"]

    async def scenario(ctx):
        await ok(ctx, "create_location", {"name": "Сокровищница", "make_current": True})
        item = await ok(ctx, "place_item", {"item_template_id": "item.longsword", "reason": "тайник"})
        uid = item["entity_id"]
        entity = ctx.world.entities[uid]
        entity.state = {**entity.state, "world_object": _world_item_state()}

        # A unique item must not merge with an otherwise identical floor stack.
        other = await ok(ctx, "place_item", {"item_template_id": "item.longsword", "reason": "запас"})
        assert other["entity_id"] != uid

        picked = await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid})
        row = next(i for i in ctx.world.inventory[hid] if i.id == picked["inventory_id"])
        assert row.world_entity_id == uid and row.qty == 1
        assert ctx.world.entities[uid].location_id is None
        assert uid not in {e.id for e in ctx.world.in_scene_entities()}
        assert not (await execute(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid}))["ok"]

        dropped = await ok(ctx, "drop_item", {"character_id": hid, "inventory_id": row.id})
        assert dropped["entity_id"] == uid
        assert ctx.world.entities[uid].location_id is not None
        again = await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": uid})
        assert again["inventory_id"] != row.id
        return uid, other["entity_id"], again["inventory_id"]

    unique_id, ordinary_id, inv_id = play(settings, cid, scenario)
    scene = _map(client, player, cid)
    assert unique_id not in {x["id"] for x in scene["around"]}
    assert ordinary_id in {x["id"] for x in scene["around"]}

    async def persisted(session):
        entity = await session.get(Entity, unique_id)
        item = await session.get(InventoryItem, inv_id)
        return entity.id, entity.location_id, entity.state["visual_key"], item.world_entity_id

    assert run(settings, persisted) == (unique_id, None, "item:weapon", unique_id)


def test_container_hides_contents_until_retrieved_and_rejects_cycle(client, admin, settings):
    import_base(settings)
    campaign, (player,), hero = party(client, admin)
    cid, hid = campaign["id"], hero["id"]

    async def setup(ctx):
        await ok(ctx, "create_location", {"name": "Кладовая", "make_current": True})
        chest = await ok(ctx, "create_container", {"name": "Сундук"})
        small = await ok(ctx, "create_container", {"name": "Коробка"})
        thing = await ok(ctx, "place_item", {"item_template_id": "item.dagger", "reason": "находка"})
        return chest["container_id"], small["container_id"], thing["entity_id"]

    chest, box, dagger = play(settings, cid, setup)

    async def store(ctx):
        assert not (
            await execute(ctx, "store_object", {"character_id": hid, "container_id": chest, "object_id": dagger})
        )["ok"]
        await ok(ctx, "open_container", {"character_id": hid, "container_id": chest})
        await ok(ctx, "open_container", {"character_id": hid, "container_id": box})
        await ok(ctx, "store_object", {"character_id": hid, "container_id": chest, "object_id": dagger})
        await ok(ctx, "store_object", {"character_id": hid, "container_id": chest, "object_id": box})
        inner = await ok(ctx, "inspect_container", {"character_id": hid, "container_id": chest})
        assert {x["id"] for x in inner["contents"]} == {box, dagger}
        cycle = await execute(ctx, "store_object", {"character_id": hid, "container_id": box, "object_id": chest})
        assert not cycle["ok"] and "потомка" in cycle["error"]
        await ok(ctx, "open_container", {"character_id": hid, "container_id": chest, "opened": False})
        assert not (
            await execute(ctx, "retrieve_object", {"character_id": hid, "container_id": chest, "object_id": dagger})
        )["ok"]

    play(settings, cid, store)
    scene = _map(client, player, cid)
    assert chest in {x["id"] for x in scene["around"]}
    assert dagger not in {x["id"] for x in scene["around"]}
    assert box not in {x["id"] for x in scene["scene_view"]}

    async def retrieve(ctx):
        await ok(ctx, "open_container", {"character_id": hid, "container_id": chest})
        await ok(ctx, "retrieve_object", {"character_id": hid, "container_id": chest, "object_id": dagger})
        picked = await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": dagger})
        return picked["inventory_id"]

    inventory_id = play(settings, cid, retrieve)
    scene = _map(client, player, cid)
    assert dagger not in {x["id"] for x in scene["around"]}

    async def persisted(session):
        en = await session.get(Entity, dagger)
        row = await session.get(InventoryItem, inventory_id)
        return en is None, row.qty

    # Ordinary items retain their original stack-delete semantics after being retrieved.
    assert run(settings, persisted) == (True, 1)
