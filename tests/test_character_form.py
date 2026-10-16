"""Physical forms survive reloads and gate inventory mutations."""

import json

import pytest

from app.agents.master.prompt_context import narration_scene
from app.tools.master.items import _world_item_state
from app.tools.registry import execute
from tests.game import import_base, party
from tests.test_world_objects_transfer import ok, play


@pytest.mark.parametrize("unique", [False, True])
def test_rat_cannot_pick_up_items_until_reverting(client, admin, settings, unique):
    import_base(settings)
    campaign, _, hero = party(client, admin)
    cid, hid = campaign["id"], hero["id"]

    async def setup(ctx):
        await ok(ctx, "create_location", {"name": "Узкий лаз", "make_current": True})
        item = await ok(ctx, "place_item", {"item_template_id": "item.longsword", "reason": "находка"})
        if unique:
            entity = ctx.world.entities[item["entity_id"]]
            entity.state = {**entity.state, "world_object": _world_item_state()}
        await ok(
            ctx,
            "set_character_form",
            {
                "character_id": hid,
                "name": "Крыса",
                "can_handle_items": False,
                "reason": "Подтверждённое превращение перед входом в лаз",
            },
        )
        return item["entity_id"]

    entity_id = play(settings, cid, setup)

    async def scenario(ctx):
        before = [(it.id, it.qty) for it in ctx.world.inventory[hid]]
        location = ctx.world.entities[entity_id].location_id
        sheet = await ok(ctx, "get_character", {"character_id": hid})
        assert sheet["current_form"]["name"] == "Крыса"
        assert "Крыса" in ctx.world.scene_table()
        narrator = json.loads(narration_scene(ctx))
        assert narrator["heroes"][0]["current_form"]["name"] == "Крыса"
        result = await execute(ctx, "pick_up_item", {"character_id": hid, "entity_id": entity_id})
        assert not result["ok"], result
        assert result["failure"]["code"] == "form_cannot_handle_items"
        assert [(it.id, it.qty) for it in ctx.world.inventory[hid]] == before
        assert ctx.world.entities[entity_id].location_id == location
        assert not any("предмет в инвентаре" in out.get("content", "") for out in ctx.outbox)
        # A refusal cannot be bypassed by creating an inventory copy.
        for tool, args in (
            ("give_item", {"item_template_id": "item.longsword", "reason": "награда"}),
            ("keep_found_item", {"name": "Кирка", "kind": "object", "how": "found", "reason": "находка"}),
        ):
            denied = await execute(ctx, tool, {"character_id": hid, **args})
            assert not denied["ok"], denied
            assert denied["failure"]["code"] == "form_cannot_handle_items"
        await ok(ctx, "set_character_form", {"character_id": hid, "name": None, "reason": "Возврат в свой облик"})
        await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": entity_id})

    play(settings, cid, scenario)


@pytest.mark.parametrize("tool", ["equip_item", "use_item"])
def test_rat_cannot_handle_existing_equipment(client, admin, settings, tool):
    import_base(settings)
    campaign, _, hero = party(client, admin)
    cid, hid = campaign["id"], hero["id"]

    async def scenario(ctx):
        item = await ok(
            ctx,
            "give_item",
            {
                "character_id": hid,
                "item_template_id": "item.potion_of_healing",
                "reason": "запас",
            },
        )
        await ok(ctx, "set_character_form", {"character_id": hid, "name": "Крыса", "reason": "Превращение в зверя"})
        row = next(it for it in ctx.world.inventory[hid] if it.id == item["inventory_id"])
        before = (row.qty, row.equipped)
        result = await execute(ctx, tool, {"character_id": hid, "inventory_id": row.id})
        assert not result["ok"], result
        assert result["failure"]["code"] == "form_cannot_handle_items"
        assert (row.qty, row.equipped) == before

    play(settings, cid, scenario)


def test_form_expiration_and_body_that_can_handle_items(client, admin, settings):
    import_base(settings)
    campaign, _, hero = party(client, admin)
    cid, hid = campaign["id"], hero["id"]

    async def scenario(ctx):
        await ok(ctx, "create_location", {"name": "Зал", "make_current": True})
        args = {"character_id": hid, "item_template_id": "item.longsword", "reason": "награда"}
        await ok(
            ctx,
            "set_character_form",
            {
                "character_id": hid,
                "name": "Человек",
                "can_handle_items": True,
                "reason": "Физическое превращение",
            },
        )
        await ok(ctx, "give_item", args)
        await ok(
            ctx,
            "set_character_form",
            {
                "character_id": hid,
                "name": "Крыса",
                "duration_seconds": 60,
                "reason": "Временное превращение",
            },
        )
        assert not (await execute(ctx, "give_item", args))["ok"]
        ctx.world.scene.game_time += 60
        assert (await ok(ctx, "get_character", {"character_id": hid}))["current_form"] is None
        assert "текущий физический облик" not in ctx.world.scene_table()
        await ok(ctx, "give_item", args)

    play(settings, cid, scenario)
