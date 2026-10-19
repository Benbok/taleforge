import pytest

from app.db.models import Message
from app.tools.registry import execute, tool_specs
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


def test_explicit_cast_selects_second_part(game):
    from app.agents.master.action_binding import bind_tool_action
    from app.tools.resolution.requests import bind_message_actions

    settings, campaign_id, hero = game

    async def check(ctx):
        ch = ctx.world.characters[hero]
        message = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=201,
            content="колдую дважды",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "cast", "spell_id": "spell.magic_missile", "target_id": hero},
                    {"verb": "cast", "spell_id": "spell.cure_wounds", "target_id": hero},
                ],
            },
        )
        ctx.session.add(message)
        await ctx.session.flush()
        refs = bind_message_actions(message, hero)
        ctx.required_actions = list(refs)

        args = {"caster_id": hero, "spell_id": "spell.cure_wounds", "target_ids": [hero]}
        # Explicitly choosing part 1
        binding = await bind_tool_action(ctx, "cast_spell", args, explicit=refs[1])
        assert binding is not None
        assert binding.ref == refs[1]
        assert binding.ref.part == 1
        assert binding.role == "finish"

    play(settings, campaign_id, [], check)


def test_two_messages_same_actor_require_source(game):
    from app.agents.master.action_binding import bind_tool_action
    from app.tools.registry import ToolError
    from app.tools.resolution.requests import bind_message_actions

    settings, campaign_id, hero = game

    async def check(ctx):
        ch = ctx.world.characters[hero]
        msg1 = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=202,
            content="осматриваюсь",
            intent={"confidence": 0.9, "actions": [{"verb": "search", "target_id": hero}]},
        )
        msg2 = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=203,
            content="ищу тайник",
            intent={"confidence": 0.9, "actions": [{"verb": "search", "target_id": hero}]},
        )
        ctx.session.add(msg1)
        ctx.session.add(msg2)
        await ctx.session.flush()
        refs1 = bind_message_actions(msg1, hero)
        refs2 = bind_message_actions(msg2, hero)
        ctx.required_actions = [*refs1, *refs2]

        args = {"character_id": hero, "skill": "perception", "target_id": hero}
        # Without explicit ref, two messages from the same actor are ambiguous
        with pytest.raises(ToolError) as exc_info:
            await bind_tool_action(ctx, "roll_check", args)
        assert exc_info.value.code == "ambiguous_action"

        # Explicit ref resolves ambiguity
        bound = await bind_tool_action(ctx, "roll_check", args, explicit=refs2[0])
        assert bound.ref.source_id == msg2.id

    play(settings, campaign_id, [], check)


def test_ambiguous_check_changes_nothing(game):
    from app.tools.resolution.requests import bind_message_actions

    settings, campaign_id, hero = game

    async def check(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=204,
            content="ищу здесь и ищу там",
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

        # Ambiguous check without action_ref
        res = await execute(
            ctx,
            "roll_check",
            {"character_id": hero, "skill": "perception", "target_id": hero, "dc": 12},
        )
        assert not res["ok"]
        assert res["failure"]["code"] == "ambiguous_action"
        assert len(ctx.events) == 0

    play(settings, campaign_id, [15], check)


def test_wrong_target_or_foreign_ref_changes_nothing(game):
    from app.tools.resolution.requests import bind_message_actions

    settings, campaign_id, hero = game

    async def check(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=205,
            content="осматриваю себя",
            intent={"confidence": 0.9, "actions": [{"verb": "search", "target_id": hero}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # Foreign campaign ref
        foreign_ref = refs[0].model_copy(update={"campaign_id": "c_foreign"})
        res1 = await execute(
            ctx,
            "roll_check",
            {
                "character_id": hero,
                "skill": "perception",
                "target_id": hero,
                "dc": 10,
                "action_ref": foreign_ref.model_dump(),
            },
        )
        assert not res1["ok"]
        assert res1["failure"]["code"] == "invalid_source"
        assert len(ctx.events) == 0

        # Wrong actor
        wrong_actor_ref = refs[0].model_copy(update={"actor_id": "ch_foreign"})
        res2 = await execute(
            ctx,
            "roll_check",
            {
                "character_id": hero,
                "skill": "perception",
                "target_id": hero,
                "dc": 10,
                "action_ref": wrong_actor_ref.model_dump(),
            },
        )
        assert not res2["ok"]
        assert len(ctx.events) == 0

    play(settings, campaign_id, [15], check)


def test_auxiliary_world_call_does_not_claim_player_part(game):
    from app.agents.master.action_binding import bind_tool_action
    from app.tools.resolution.requests import bind_message_actions

    settings, campaign_id, hero = game

    async def check(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=206,
            content="жду",
            intent={"confidence": 0.9, "actions": [{"verb": "inspect", "target_id": hero}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # Auxiliary tool like spawn_entity has no player action binding
        binding = await bind_tool_action(
            ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"}
        )
        assert binding is None
        assert hero not in ctx.closed

    play(settings, campaign_id, [], check)


def test_tool_schema_accepts_metadata_without_handler_field(game):
    from app.tools.resolution.requests import bind_message_actions

    settings, campaign_id, hero = game

    async def check(ctx):
        # 1. tool_specs has action_ref in properties
        specs = tool_specs(ctx.world, ["roll_check"])
        assert len(specs) == 1
        props = specs[0]["function"]["parameters"]["properties"]
        assert "action_ref" in props

        # 2. execute accepts action_ref without handler raising extra fields error
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=207,
            content="проверка",
            intent={"confidence": 0.9, "actions": [{"verb": "search", "target_id": hero}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        res = await execute(
            ctx,
            "roll_check",
            {
                "character_id": hero,
                "stat": "perception",
                "difficulty": "dc.easy",
                "reason": "поиск",
                "target_id": hero,
                "action_ref": refs[0].model_dump(),
            },
        )
        assert res["ok"], res
        assert ctx.current_binding is not None
        assert ctx.current_binding.ref == refs[0]

    play(settings, campaign_id, [15], check)


def test_feeding_the_recipient_resolves_a_give_part():
    # плейтест 19.10: «даю ягоду раненому стражнику» — игрок хотел, чтобы тот съел ягоду; use_item на получателя
    # отклонялся как «нет подходящей заявки», и стражник оставался без лечения
    from app.agents.master.action_binding import is_action_compatible

    give = {"verb": "give", "target_id": "npc", "instrument_id": "berry"}
    assert is_action_compatible("use_item", {"inventory_id": "berry", "target_id": "npc"}, give)
    assert not is_action_compatible("use_item", {"inventory_id": "berry", "target_id": "other"}, give)
    assert not is_action_compatible("use_item", {"inventory_id": "rope", "target_id": "npc"}, give)
    assert not is_action_compatible("use_item", {"inventory_id": "berry"}, give)  # съесть самому — не «отдать»


def test_helping_an_ally_outside_combat_closes_with_auto_success():
    # плейтест 19.10: «я тебе помогу, пошли» — часть help не находила инструмент, и ход заканчивался отменой
    from app.agents.master.action_binding import is_action_compatible

    help_part = {"verb": "help", "target_id": "en_guard"}
    assert is_action_compatible("auto_success", {"character_id": "ch1", "reason": "помог встать"}, help_part)
    assert not is_action_compatible("auto_success", {"character_id": "ch1"}, {"verb": "attack"})


def test_creative_item_tools_bind_to_the_verbs_players_use():
    # плейтест 19.10: keep_found_item и родственные инструменты не подходили ни к одному глаголу, кроме custom,
    # и «беру всё с собой» оставалось без пути создать находку (мастер брал auto_success)
    from app.agents.master.action_binding import is_action_compatible as ok

    for tool in ("keep_found_item", "invent_item", "give_item"):
        assert all(ok(tool, {"character_id": "c"}, {"verb": v}) for v in ("pick_up", "search", "interact", "inspect"))
    assert ok("place_item", {}, {"verb": "pick_up"})
    assert all(ok(t, {}, {"verb": "search"}) for t in ("create_container", "add_landmark"))
    assert not ok("keep_found_item", {"character_id": "c"}, {"verb": "attack"})
    assert not ok("create_container", {}, {"verb": "attack"})


def test_taking_a_new_find_binds_to_keep_found_item_not_auto_success(game):
    # плейтест 19.10: «беру все это с собой» — keep_found_item отклонялся как no_matching_action, а auto_success
    # проходил и закрывал заявку без единого предмета в инвентаре
    from app.agents.master.action_binding import bind_tool_action
    from app.tools.registry import ToolError
    from app.tools.resolution.requests import bind_message_actions

    settings, campaign_id, hero = game

    async def check(ctx):
        ch = ctx.world.characters[hero]
        message = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=204,
            content="беру бумаги с собой",
            intent={"confidence": 0.9, "actions": [{"verb": "pick_up"}]},
        )
        ctx.session.add(message)
        await ctx.session.flush()
        ctx.required_actions = list(bind_message_actions(message, hero))

        kept = await bind_tool_action(ctx, "keep_found_item", {"character_id": hero, "name": "Бумаги"})
        assert kept is not None and kept.role == "finish"
        with pytest.raises(ToolError) as refused:
            await bind_tool_action(ctx, "auto_success", {"character_id": hero, "reason": "взял"})
        assert refused.value.code == "no_matching_action"

    play(settings, campaign_id, [], check)
