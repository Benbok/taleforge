from app.db.models import Entity, InventoryItem, Message
from app.tools.master.base import FOUND_ITEM
from app.tools.registry import execute
from app.tools.resolution.context import refresh_world
from app.tools.resolution.requests import (
    bind_message_actions,
    bound_tool_key,
    get_action_progress,
)
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


def test_cast_and_search_discovery_complete_both(game):
    from app.agents.master.action_progress import finalize_action_parts

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        ch.sheet = {**ch.sheet, "class_id": "class.druid", "spells": [], "prepared": ["spell.goodberry"]}
        ch.resources = {"slots_used": {}}
        ctx.world.invalidate(hero)

        desk = Entity(
            id="desk", campaign_id=campaign_id, kind="object", name="Стол", location_id=ch.location_id, state={}
        )
        ctx.session.add(desk)
        await refresh_world(ctx)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=401,
            content="творю ягоды и осматриваю стол",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "cast", "spell_id": "spell.goodberry"},
                    {"verb": "search", "target_id": "desk"},
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # 1. Cast completes part 0
        cast_args = {"caster_id": hero, "spell_id": "spell.goodberry", "action_ref": refs[0].model_dump()}
        k_cast = await bound_tool_key(ctx, "cast_spell", cast_args, "call_cast")
        res_cast = await execute(ctx, "cast_spell", cast_args, key=k_cast)
        assert res_cast["ok"]
        p0 = get_action_progress(msg.data, 0)
        assert p0.status == "completed"

        # 2. Search check succeeds -> part 1 is intermediate (still pending)
        check_args = {
            "character_id": hero,
            "stat": "perception",
            "target_id": "desk",
            "difficulty": "dc.easy",
            "reason": "осмотр стола",
            "action_ref": refs[1].model_dump(),
        }
        k_check = await bound_tool_key(ctx, "roll_check", check_args, "call_check")
        res_check = await execute(ctx, "roll_check", check_args, key=k_check)
        assert res_check["ok"] and res_check["result"]["success"] is True

        p1_mid = get_action_progress(msg.data, 1)
        assert p1_mid.status != "completed"

        # 3. Discovery via place_item links to check event and confirms part 1
        place_args = {
            "item_template_id": "item.dagger",
            "location_id": ch.location_id,
            "reason": "находка в столе",
            "discovery_check_event_id": res_check["event_id"],
            "action_ref": refs[1].model_dump(),
        }
        k_place = await bound_tool_key(ctx, "place_item", place_args, "call_place")
        res_place = await execute(ctx, "place_item", place_args, key=k_place)
        assert res_place["ok"]

        await finalize_action_parts(ctx)
        p1 = get_action_progress(msg.data, 1)
        assert p1.status == "completed"
        assert hero in ctx.closed

    play(settings, campaign_id, [18], scenario)


def test_successful_search_waits_for_world_confirmation(game):
    from app.agents.master.action_progress import finalize_action_parts, unresolved_searches

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        desk = Entity(
            id="desk", campaign_id=campaign_id, kind="object", name="Стол", location_id=ch.location_id, state={}
        )
        ctx.session.add(desk)
        await refresh_world(ctx)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=402,
            content="осматриваю стол",
            intent={"confidence": 0.9, "actions": [{"verb": "search", "target_id": "desk"}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        check_args = {
            "character_id": hero,
            "stat": "perception",
            "target_id": "desk",
            "difficulty": "dc.easy",
            "reason": "осмотр стола",
            "action_ref": refs[0].model_dump(),
        }
        k_check = await bound_tool_key(ctx, "roll_check", check_args, "call_check")
        res_check = await execute(ctx, "roll_check", check_args, key=k_check)
        assert res_check["ok"] and res_check["result"]["success"] is True

        # Search is unresolved before world confirmation
        pending = unresolved_searches(ctx)
        assert refs[0] in pending

        # Finalize without discovery -> unhandled
        await finalize_action_parts(ctx)
        p0 = get_action_progress(msg.data, 0)
        assert p0.status == "unhandled"

    play(settings, campaign_id, [19], scenario)


def test_failed_search_completes_without_reroll(game):
    from app.agents.master.action_progress import finalize_action_parts, unresolved_searches

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        desk = Entity(
            id="desk", campaign_id=campaign_id, kind="object", name="Стол", location_id=ch.location_id, state={}
        )
        ctx.session.add(desk)
        await refresh_world(ctx)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=403,
            content="осматриваю стол",
            intent={"confidence": 0.9, "actions": [{"verb": "search", "target_id": "desk"}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        check_args = {
            "character_id": hero,
            "stat": "perception",
            "target_id": "desk",
            "difficulty": "dc.hard",
            "reason": "осмотр стола",
            "action_ref": refs[0].model_dump(),
        }
        k_check = await bound_tool_key(ctx, "roll_check", check_args, "call_check")
        res_check = await execute(ctx, "roll_check", check_args, key=k_check)
        assert res_check["ok"] and res_check["result"]["success"] is False

        # Failed search is terminal, not pending
        pending = unresolved_searches(ctx)
        assert len(pending) == 0

        await finalize_action_parts(ctx)
        p0 = get_action_progress(msg.data, 0)
        assert p0.status == "completed"
        assert p0.result is not None and p0.result.game_outcome == "failure"
        assert hero in ctx.closed

    play(settings, campaign_id, [1], scenario)


def test_discovery_cannot_complete_second_search(game):
    from app.agents.master.action_progress import finalize_action_parts

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        desk = Entity(
            id="desk", campaign_id=campaign_id, kind="object", name="Стол", location_id=ch.location_id, state={}
        )
        chest = Entity(
            id="chest", campaign_id=campaign_id, kind="object", name="Сундук", location_id=ch.location_id, state={}
        )
        ctx.session.add_all([desk, chest])
        await refresh_world(ctx)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=404,
            content="осматриваю стол и сундук",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "search", "target_id": "desk"},
                    {"verb": "search", "target_id": "chest"},
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        args0 = {
            "character_id": hero,
            "stat": "perception",
            "target_id": "desk",
            "difficulty": "dc.easy",
            "reason": "стол",
            "action_ref": refs[0].model_dump(),
        }
        res0 = await execute(ctx, "roll_check", args0, key=await bound_tool_key(ctx, "roll_check", args0, "c0"))
        assert res0["ok"] and res0["result"]["success"] is True

        args1 = {
            "character_id": hero,
            "stat": "perception",
            "target_id": "chest",
            "difficulty": "dc.easy",
            "reason": "сундук",
            "action_ref": refs[1].model_dump(),
        }
        res1 = await execute(ctx, "roll_check", args1, key=await bound_tool_key(ctx, "roll_check", args1, "c1"))
        assert res1["ok"] and res1["result"]["success"] is True

        # Confirm only desk
        place_args = {
            "item_template_id": "item.dagger",
            "location_id": ch.location_id,
            "reason": "находка в столе",
            "discovery_check_event_id": res0["event_id"],
            "action_ref": refs[0].model_dump(),
        }
        await execute(ctx, "place_item", place_args, key=await bound_tool_key(ctx, "place_item", place_args, "cp"))

        await finalize_action_parts(ctx)
        p0 = get_action_progress(msg.data, 0)
        p1 = get_action_progress(msg.data, 1)

        assert p0.status == "completed"
        # Chest discovery was NOT made, so part 1 is unhandled, not completed
        assert p1.status == "unhandled"
        assert hero not in ctx.closed

    play(settings, campaign_id, [19, 18], scenario)


def test_auto_success_cannot_overwrite_failed_check(game):
    from app.agents.master.action_progress import finalize_action_parts

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        desk = Entity(
            id="desk", campaign_id=campaign_id, kind="object", name="Стол", location_id=ch.location_id, state={}
        )
        ctx.session.add(desk)
        await refresh_world(ctx)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=405,
            content="осматриваю стол",
            intent={"confidence": 0.9, "actions": [{"verb": "search", "target_id": "desk"}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # 1. Roll check fails
        check_args = {
            "character_id": hero,
            "stat": "perception",
            "target_id": "desk",
            "difficulty": "dc.hard",
            "reason": "осмотр стола",
            "action_ref": refs[0].model_dump(),
        }
        res_check = await execute(ctx, "roll_check", check_args, key="c1")
        assert res_check["ok"] and res_check["result"]["success"] is False

        # 2. auto_success attempt on the same part must be rejected or not overwrite failure
        auto_args = {
            "character_id": hero,
            "reason": "авто-успех после провала",
            "action_ref": refs[0].model_dump(),
        }
        res_auto = await execute(ctx, "auto_success", auto_args, key="c2")
        assert not res_auto["ok"]

        await finalize_action_parts(ctx)
        p0 = get_action_progress(msg.data, 0)
        assert p0.status == "completed"
        assert p0.result is not None and p0.result.game_outcome == "failure"

    play(settings, campaign_id, [1], scenario)


def test_argument_error_allows_one_repair_per_part(game):
    from app.agents.master.resolution import permit_repair
    from app.core.resolution.contracts import FailureInfo, ResolutionResult
    from app.db.models import MasterTurn
    from app.tools.resolution.requests import record_attempt

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        turn = MasterTurn(id="t_test", campaign_id=campaign_id, status="running")
        ctx.session.add(turn)
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            turn_id="t_test",
            kind="action",
            seq=406,
            content="действие",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "search", "target_id": hero},
                    {"verb": "search", "target_id": hero},
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        bad0 = ResolutionResult(
            execution="denied",
            failure=FailureInfo(
                code="invalid_arguments",
                category="invalid_arguments",
                rolled_back=True,
                attempt_id="",
            ),
        )
        await record_attempt(ctx, refs[0], "noncombat.interaction", bad0)

        # Part 0 permits 1 repair after error
        assert await permit_repair(ctx, refs[0]) is True
        assert await permit_repair(ctx, refs[0]) is False

        bad1 = ResolutionResult(
            execution="denied",
            failure=FailureInfo(
                code="invalid_arguments",
                category="invalid_arguments",
                rolled_back=True,
                attempt_id="",
            ),
        )
        await record_attempt(ctx, refs[1], "noncombat.interaction", bad1)

        # Part 1 still has its own independent repair allowance
        assert await permit_repair(ctx, refs[1]) is True
        assert await permit_repair(ctx, refs[1]) is False

    play(settings, campaign_id, [], scenario)


def test_staff_lever_alternative_path_completes_same_action(game):
    from app.agents.master.action_progress import finalize_action_parts

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        # Staff is a found item with no use mechanics
        staff = InventoryItem(
            character_id=hero,
            item_template_id=FOUND_ITEM,
            display_name="Деревянный посох",
            qty=1,
            equipped=True,
        )
        ctx.session.add(staff)

        loc_id = "loc_dungeon"
        ch.location_id = loc_id
        loc = Entity(
            id=loc_id,
            campaign_id=campaign_id,
            kind="location",
            name="Подземелье",
            state={
                "sketch": {
                    "shape": "room",
                    "cols": 6,
                    "rows": 4,
                    "party": [1, 2],
                    "exits": [{"name": "решётка", "kind": "bars", "side": "n", "at": 1, "state": "locked", "to": None}],
                    "features": [],
                }
            },
        )
        ctx.world.scene.location_id = loc_id
        ctx.session.add_all([ctx.world.scene, loc])
        await ctx.session.flush()
        await refresh_world(ctx)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=407,
            content="использую посох как рычаг чтобы открыть решётку",
            intent={"confidence": 0.9, "actions": [{"verb": "interact", "target_id": "решётка"}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # 1. use_item fails with item_use_unsupported
        use_args = {
            "character_id": hero,
            "inventory_id": staff.id,
            "action_ref": refs[0].model_dump(),
        }
        res_use = await execute(ctx, "use_item", use_args, key="call_use")
        assert not res_use["ok"]
        assert res_use["failure"]["code"] == "item_use_unsupported"

        # 2. Alternative roll_check for strength succeeds
        check_args = {
            "character_id": hero,
            "stat": "athletics",
            "difficulty": "dc.medium",
            "reason": "отжать решётку посохом",
            "action_ref": refs[0].model_dump(),
        }
        res_check = await execute(ctx, "roll_check", check_args, key="call_str")
        assert res_check["ok"] and res_check["result"]["success"] is True

        # 3. edit_sketch unlocks the passage
        sketch_args = {
            "location_id": ch.location_id,
            "action": "unlock",
            "target": "решётка",
            "action_ref": refs[0].model_dump(),
        }
        res_sketch = await execute(ctx, "edit_sketch", sketch_args, key="call_sketch")
        assert res_sketch["ok"], res_sketch

        await finalize_action_parts(ctx)
        p0 = get_action_progress(msg.data, 0)
        assert p0.status == "completed"
        assert p0.result is not None and p0.result.game_outcome == "success"
        assert hero in ctx.closed

    play(settings, campaign_id, [14], scenario)


def test_lever_check_without_unlock_is_not_completed(game):
    from app.agents.master.action_progress import finalize_action_parts

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        staff = InventoryItem(
            character_id=hero,
            item_template_id=FOUND_ITEM,
            display_name="Деревянный посох",
            qty=1,
            equipped=True,
        )
        ctx.session.add(staff)

        loc_id = "loc_dungeon"
        ch.location_id = loc_id
        loc = Entity(
            id=loc_id,
            campaign_id=campaign_id,
            kind="location",
            name="Подземелье",
            state={
                "sketch": {
                    "shape": "room",
                    "cols": 6,
                    "rows": 4,
                    "party": [1, 2],
                    "exits": [{"name": "решётка", "kind": "bars", "side": "n", "at": 1, "state": "locked", "to": None}],
                    "features": [],
                }
            },
        )
        ctx.world.scene.location_id = loc_id
        ctx.session.add_all([ctx.world.scene, loc])
        await ctx.session.flush()
        await refresh_world(ctx)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=408,
            content="использую посох как рычаг чтобы открыть решётку",
            intent={"confidence": 0.9, "actions": [{"verb": "interact", "target_id": "решётка"}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # 1. use_item fails with item_use_unsupported
        use_args = {
            "character_id": hero,
            "inventory_id": staff.id,
            "action_ref": refs[0].model_dump(),
        }
        await execute(ctx, "use_item", use_args, key="call_use")

        # 2. Check succeeds
        check_args = {
            "character_id": hero,
            "stat": "athletics",
            "difficulty": "dc.medium",
            "reason": "отжать решётку посохом",
            "action_ref": refs[0].model_dump(),
        }
        await execute(ctx, "roll_check", check_args, key="call_str")

        # 3. BUT edit_sketch unlock is never called!
        await finalize_action_parts(ctx)
        p0 = get_action_progress(msg.data, 0)
        assert p0.status != "completed"
        assert p0.status == "unhandled"

    play(settings, campaign_id, [14], scenario)


def test_neighbor_unlock_does_not_complete_failed_item_action(game):
    from app.agents.master.action_progress import finalize_action_parts

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        staff = InventoryItem(
            character_id=hero,
            item_template_id=FOUND_ITEM,
            display_name="Деревянный посох",
            qty=1,
            equipped=True,
        )
        ctx.session.add(staff)

        loc_id = "loc_dungeon"
        ch.location_id = loc_id
        loc = Entity(
            id=loc_id,
            campaign_id=campaign_id,
            kind="location",
            name="Подземелье",
            state={
                "sketch": {
                    "shape": "room",
                    "cols": 6,
                    "rows": 4,
                    "party": [1, 2],
                    "exits": [
                        {"name": "решётка", "kind": "bars", "side": "n", "at": 1, "state": "locked", "to": None},
                        {"name": "соседняя дверь", "kind": "door", "side": "e", "at": 1, "state": "locked", "to": None},
                    ],
                    "features": [],
                }
            },
        )
        ctx.world.scene.location_id = loc_id
        ctx.session.add_all([ctx.world.scene, loc])
        await ctx.session.flush()
        await refresh_world(ctx)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=409,
            content="использую посох на решётке",
            intent={"confidence": 0.9, "actions": [{"verb": "interact", "target_id": "решётка"}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # 1. use_item fails
        use_args = {
            "character_id": hero,
            "inventory_id": staff.id,
            "action_ref": refs[0].model_dump(),
        }
        await execute(ctx, "use_item", use_args, key="call_use")

        # 2. Check succeeds
        check_args = {
            "character_id": hero,
            "stat": "athletics",
            "difficulty": "dc.medium",
            "reason": "отжать",
            "action_ref": refs[0].model_dump(),
        }
        await execute(ctx, "roll_check", check_args, key="call_str")

        # 3. edit_sketch unlocks NEIGHBOR door, NOT the target "решётка"
        sketch_args = {
            "location_id": ch.location_id,
            "action": "unlock",
            "target": "соседняя дверь",
            "action_ref": refs[0].model_dump(),
        }
        await execute(ctx, "edit_sketch", sketch_args, key="call_sketch")

        await finalize_action_parts(ctx)
        p0 = get_action_progress(msg.data, 0)
        assert p0.status != "completed"
        assert p0.status == "unhandled"

    play(settings, campaign_id, [14], scenario)
