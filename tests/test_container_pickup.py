# ruff: noqa: F811 -- shared integration fixtures
"""Pickups and container searches must resolve the player's actual request."""

import pytest

from app.agents import intent as intents
from app.db.models import Event, InventoryItem, Message
from app.tools.master.items import _world_item_state
from app.tools.registry import execute
from app.tools.resolution.requests import bind_message_actions
from tests.game import import_base, party
from tests.test_intent_recovery import admin_g, dice, game_client, llm, rows  # noqa: F401
from tests.test_world_objects_transfer import ok, play
from tests.test_ws import connect, wait_message_result


async def setup_container(ctx, hero_id, *, unique=False):
    await ok(ctx, "create_location", {"name": "Пещера", "make_current": True})
    box = (await ok(ctx, "create_container", {"name": "Старый рюкзак"}))["container_id"]
    item = (await ok(ctx, "place_item", {"item_template_id": "item.potion_of_healing", "reason": "находка"}))[
        "entity_id"
    ]
    if unique:
        entity = ctx.world.entities[item]
        entity.state = {**entity.state, "world_object": _world_item_state()}
    await ok(ctx, "open_container", {"character_id": hero_id, "container_id": box})
    await ok(ctx, "store_object", {"character_id": hero_id, "container_id": box, "object_id": item})
    return box, item


@pytest.mark.parametrize("unique", [False, True])
def test_pick_up_visible_container_item_directly(client, admin, settings, unique):
    import_base(settings)
    campaign, _, hero = party(client, admin)
    hid = hero["id"]

    async def scenario(ctx):
        box, item = await setup_container(ctx, hid, unique=unique)
        ch = ctx.world.characters[hid]
        _, values = intents.context_for(ctx.world, ch)
        assert item in values["target_id"]
        assert item in ctx.world.valid_ids()["scene_items"]
        parsed = intents.check({"actions": [{"verb": "pick_up", "target_id": item}]}, ctx.world, ch)
        assert parsed.intent["actions"][0]["target_id"] == item
        assert intents.routable_tool_call(parsed.intent, ctx.world) == (
            "pick_up_item",
            {"character_id": hid, "entity_id": item},
        )
        result = await ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": item})
        row = next(it for it in ctx.world.inventory[hid] if it.id == result["inventory_id"])
        assert row.item_template_id == "item.potion_of_healing"
        assert row.world_entity_id == (item if unique else None)
        inside = await ok(ctx, "inspect_container", {"character_id": hid, "container_id": box})
        assert inside["contents"] == []

    play(settings, campaign["id"], scenario)


def test_search_container_completes_bound_search_request(client, admin, settings):
    import_base(settings)
    campaign, _, hero = party(client, admin)
    hid = hero["id"]

    async def scenario(ctx):
        box, item = await setup_container(ctx, hid)
        ctx.closed.clear()
        msg = Message(
            campaign_id=campaign["id"],
            seat_id=ctx.world.characters[hid].seat_id,
            kind="action",
            seq=201,
            content="Обыскиваю: Старый рюкзак",
            intent={"confidence": 1, "actions": [{"verb": "search", "target_id": box}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hid)
        ctx.required_actions = list(refs)
        assert intents.routable_tool_call({**msg.intent, "character_id": hid}, ctx.world) == (
            "search_container",
            {"character_id": hid, "container_id": box},
        )
        result = await execute(
            ctx,
            "search_container",
            {
                "character_id": hid,
                "container_id": box,
                "action_ref": refs[0].model_dump(),
            },
        )
        assert result["ok"], result
        assert result["result"]["contents"][0]["id"] == item
        assert hid in ctx.closed
        assert msg.data["resolution_progress"]["0"]["status"] == "completed"

    play(settings, campaign["id"], scenario)


@pytest.mark.parametrize("blocked", ["closed", "hidden", "outer_closed", "other_room"])
def test_container_pickup_does_not_bypass_access(client, admin, settings, blocked):
    import_base(settings)
    campaign, _, hero = party(client, admin)
    hid = hero["id"]

    async def scenario(ctx):
        box, item = await setup_container(ctx, hid)
        if blocked == "closed":
            await ok(ctx, "open_container", {"character_id": hid, "container_id": box, "opened": False})
        elif blocked == "hidden":
            entity = ctx.world.entities[item]
            entity.state = {**entity.state, "hidden": True}
        elif blocked == "outer_closed":
            outer = (await ok(ctx, "create_container", {"name": "Сундук"}))["container_id"]
            await ok(ctx, "open_container", {"character_id": hid, "container_id": outer})
            await ok(ctx, "store_object", {"character_id": hid, "container_id": outer, "object_id": box})
            await ok(ctx, "open_container", {"character_id": hid, "container_id": outer, "opened": False})
        else:
            await ok(ctx, "create_location", {"name": "Другая комната", "make_current": True})
        assert item not in intents.context_for(ctx.world, ctx.world.characters[hid])[1]["target_id"]
        before = [(it.id, it.qty) for it in ctx.world.inventory[hid]]
        result = await execute(ctx, "pick_up_item", {"character_id": hid, "entity_id": item})
        assert not result["ok"], result
        assert [(it.id, it.qty) for it in ctx.world.inventory[hid]] == before
        assert ctx.world.entities[item].state["world_object"]["container_id"] == box

    play(settings, campaign["id"], scenario)


def test_item_card_pickup_skips_model_parser(game_client, admin_g, llm, settings):
    campaign, _, hero = party(game_client, admin_g)
    hid = hero["id"]

    async def setup(ctx):
        _, item = await setup_container(ctx, hid)
        return item, ctx.world.characters[hid].seat_id

    item, seat_id = play(settings, campaign["id"], setup)
    before = len(llm.requests)
    parsed = game_client.portal.call(
        game_client.app.state.master.parse_intent,
        campaign["id"],
        seat_id,
        "Подбираю: Зелье лечения",
    )
    assert parsed.intent, parsed
    assert parsed.intent["character_id"] == hid
    assert parsed.intent["actions"][0]["target_id"] == item
    assert len(llm.requests) == before


@pytest.mark.parametrize("verb", ["search", "pick_up"])
def test_container_actions_complete_a_real_game_turn(game_client, admin_g, llm, settings, verb):
    campaign, (player,), hero = party(game_client, admin_g)
    cid, hid = campaign["id"], hero["id"]

    async def setup(ctx):
        return await setup_container(ctx, hid)

    box, item = play(settings, cid, setup)
    llm.replies += [{"text": "Герой осматривает находку."}]
    text = "Обыскиваю: Старый рюкзак" if verb == "search" else "Подбираю: Зелье лечения"
    payload = {"kind": "action", "text": text, "client_id": "container-action"}
    if verb == "search":  # This is the existing container-card button payload.
        payload["quick"] = {"actions": [{"verb": verb, "target_id": box}]}
    with connect(game_client, player, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": payload})
        accepted = wait_message_result(ws, client_id="container-action", timeout_s=5)
        assert accepted["type"] == "message.new", accepted
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    (message,) = rows(settings, Message, Message.kind == "action")
    assert message.data["resolution_progress"]["0"]["status"] == "completed"
    assert rows(settings, Event, Event.tool == "cancel_action") == []
    assert rows(settings, Event, Event.tool == "roll_check") == []
    if verb == "pick_up":
        assert len(rows(settings, InventoryItem, InventoryItem.item_template_id == "item.potion_of_healing")) == 1
