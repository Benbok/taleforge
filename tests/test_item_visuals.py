"""Регрессии интеграции item_template.visual_key с предметами сцены и картой."""

from app.db.models import Entity
from tests.game import import_base, party, run
from tests.test_map import _map, _ok, _play


def test_visual_key_follows_template_stacks_and_inventory(client, admin, settings):
    import_base(settings)
    c, (player,), hero = party(client, admin)
    cid, hid = c["id"], hero["id"]

    async def setup(ctx):
        await _ok(ctx, "create_location", {"name": "Склад алхимика", "make_current": True})
        pot = await _ok(ctx, "place_item", {"item_template_id": "item.potion_of_healing", "qty": 2, "reason": "добыча"})
        again = await _ok(ctx, "place_item", {"item_template_id": "item.potion_of_healing", "reason": "ещё добыча"})
        assert pot["entity_id"] == again["entity_id"]  # стопки по-прежнему объединяются
        scroll = await _ok(ctx, "place_item", {"item_template_id": "item.scroll_magic_missile", "reason": "добыча"})
        sword = await _ok(ctx, "place_item", {"item_template_id": "item.dagger", "reason": "добыча"})
        armor = await _ok(ctx, "place_item", {"item_template_id": "item.leather", "reason": "добыча"})
        gift = await _ok(ctx, "give_item", {
            "character_id": hid, "item_template_id": "item.potion_of_healing", "qty": 2, "reason": "награда"
        })
        dropped = await _ok(ctx, "drop_item", {
            "character_id": hid, "inventory_id": gift["inventory_id"], "qty": 1
        })
        return pot["entity_id"], scroll["entity_id"], sword["entity_id"], armor["entity_id"], dropped["entity_id"]

    potion, scroll, sword, armor, dropped = _play(settings, cid, setup)

    async def read(s):
        return {eid: (await s.get(Entity, eid)).state for eid in (potion, scroll, sword, armor, dropped)}

    states = run(settings, read)
    assert states[potion]["qty"] == 3
    for eid in (potion, dropped):
        assert states[eid]["visual_key"] == "item:potion"
    assert states[scroll]["visual_key"] == "item:scroll"
    assert states[sword]["visual_key"] == "item:weapon"
    assert "visual_key" not in states[armor]  # старые шаблоны используют fallback

    m = _map(client, player, cid)
    around = {x["id"]: x for x in m["around"]}
    scene = {x["id"]: x for x in m["scene_view"]}
    for eid in (potion, scroll, sword, armor, dropped):
        assert around[eid]["visual_key"] == scene[eid]["visual_key"]
    assert around[potion]["visual_key"] == "item:potion"
    assert around[armor]["visual_key"] is None

    async def take_and_replace(ctx):
        found = await _ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": potion, "qty": 1})
        again = await _ok(ctx, "drop_item", {"character_id": hid, "inventory_id": found["inventory_id"], "qty": 1})
        return again["entity_id"]

    restored = _play(settings, cid, take_and_replace)
    m = _map(client, player, cid)
    assert next(x for x in m["around"] if x["id"] == restored)["visual_key"] == "item:potion"
    assert next(x for x in m["around"] if x["id"] == potion)["visual_key"] == "item:potion"
