import asyncio

import pytest

from app.core.resolution.contracts import ActionRef
from app.db.models import Campaign, Entity, Message
from app.db.session import make_sessionmaker
from app.tools.registry import execute
from app.tools.resolution.context import refresh_world
from app.tools.resolution.requests import (
    action_tool_key,
    bind_message_actions,
    bound_tool_key,
)
from app.tools.runtime import open_context
from tests.game import QueueDice, run
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


def test_action_tool_key_format():
    ref = ActionRef(campaign_id="c_1", source_kind="message", source_id="m_1", actor_id="ch_1", part=0)
    k1 = action_tool_key(ref, "roll_check", "primary_check")
    k2 = action_tool_key(ref, "roll_check", "primary_check")
    assert k1 == k2
    assert len(k1) == 64

    ref1 = ActionRef(campaign_id="c_1", source_kind="message", source_id="m_1", actor_id="ch_1", part=1)
    k3 = action_tool_key(ref1, "roll_check", "primary_check")
    assert k1 != k3


def test_same_part_new_call_id_rolls_once(game):
    settings, campaign_id, hero = game

    async def check(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=301,
            content="ищу тайник",
            intent={"confidence": 0.9, "actions": [{"verb": "search", "target_id": hero}]},
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        args = {
            "character_id": hero,
            "stat": "perception",
            "target_id": hero,
            "difficulty": "dc.easy",
            "reason": "поиск",
        }
        key1 = await bound_tool_key(ctx, "roll_check", args, "call1")
        first = await execute(ctx, "roll_check", args, key=key1)
        assert first["ok"], first
        assert not first.get("repeated")

        key2 = await bound_tool_key(ctx, "roll_check", args, "call2")
        # Same part must produce the exact same bound idempotency key despite different default call_id
        assert key1 == key2

        repeated = await execute(ctx, "roll_check", args, key=key2)
        assert repeated.get("repeated") and repeated["result"] == first["result"]
        # Dice queue should have had only 1 roll consumed
        assert ctx.dice.queue == [19]

    play(settings, campaign_id, [5, 19], check)


def test_two_search_parts_have_distinct_rolls(game):
    settings, campaign_id, hero = game

    async def check(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=302,
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
        desk = Entity(
            id="desk", campaign_id=campaign_id, kind="object", name="Стол", location_id=ch.location_id, state={}
        )
        chest = Entity(
            id="chest", campaign_id=campaign_id, kind="object", name="Сундук", location_id=ch.location_id, state={}
        )
        ctx.session.add_all([desk, chest])
        await refresh_world(ctx)

        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        args0 = {
            "character_id": hero,
            "stat": "perception",
            "target_id": "desk",
            "difficulty": "dc.easy",
            "reason": "осмотр стола",
            "action_ref": refs[0].model_dump(),
        }
        args1 = {
            "character_id": hero,
            "stat": "perception",
            "target_id": "chest",
            "difficulty": "dc.easy",
            "reason": "осмотр сундука",
            "action_ref": refs[1].model_dump(),
        }

        key0 = await bound_tool_key(ctx, "roll_check", args0, "call_desk")
        key1 = await bound_tool_key(ctx, "roll_check", args1, "call_chest")
        assert key0 != key1

        first = await execute(ctx, "roll_check", args0, key=key0)
        second = await execute(ctx, "roll_check", args1, key=key1)

        assert first["ok"], first
        assert not first.get("repeated")
        assert second["ok"] and not second.get("repeated")
        assert first["event_id"] != second["event_id"]
        # Both dice rolls consumed
        assert len(ctx.dice.queue) == 0

    play(settings, campaign_id, [5, 15], check)


def test_two_cast_parts_spend_separately_but_replay_spends_once(game):
    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        ch.sheet = {**ch.sheet, "class_id": "class.druid", "spells": [], "prepared": ["spell.goodberry"]}
        ch.resources = {"slots_used": {}}
        ctx.world.invalidate(hero)

        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=303,
            content="дважды творю ягоды",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "cast", "spell_id": "spell.goodberry"},
                    {"verb": "cast", "spell_id": "spell.goodberry"},
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        args0 = {"caster_id": hero, "spell_id": "spell.goodberry", "action_ref": refs[0].model_dump()}
        key0 = await bound_tool_key(ctx, "cast_spell", args0, "call0")
        cast0 = await execute(ctx, "cast_spell", args0, key=key0)
        assert cast0["ok"], cast0
        assert not cast0.get("repeated")
        assert ch.resources.get("slots_used", {}).get("1") == 1

        # Replay part 0 with a new call id -> repeats without spending slot
        key0_retry = await bound_tool_key(ctx, "cast_spell", args0, "call0_retry")
        assert key0_retry == key0
        replay0 = await execute(ctx, "cast_spell", args0, key=key0_retry)
        assert replay0["ok"]
        assert replay0.get("repeated")
        assert ch.resources.get("slots_used", {}).get("1") == 1

        # Cast part 1 -> spends second slot
        args1 = {"caster_id": hero, "spell_id": "spell.goodberry", "action_ref": refs[1].model_dump()}
        key1 = await bound_tool_key(ctx, "cast_spell", args1, "call1")
        assert key1 != key0
        cast1 = await execute(ctx, "cast_spell", args1, key=key1)
        assert cast1["ok"]
        assert not cast1.get("repeated")
        assert ch.resources.get("slots_used", {}).get("1") == 2

    play(settings, campaign_id, [], scenario)


def test_concurrent_same_part_has_one_effect(game):
    settings, campaign_id, hero = game
    if not settings.database_url.startswith("postgresql"):
        pytest.skip("real concurrent row-lock test requires PostgreSQL")

    async def prepare(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=304,
            content="проверяю дверь",
            intent={"confidence": 0.9, "actions": [{"verb": "search", "target_id": "door"}]},
        )
        door = Entity(
            id="door", campaign_id=campaign_id, kind="object", name="Дверь", location_id=ch.location_id, state={}
        )
        ctx.session.add(door)
        await refresh_world(ctx)
        refs = bind_message_actions(msg, hero)
        return refs[0]

    ref = play(settings, campaign_id, [], prepare)

    async def concurrent(session):
        factory = make_sessionmaker(session.bind)
        loaded = 0
        ready = asyncio.Event()
        dice = QueueDice([7, 18])

        async def worker(index):
            nonlocal loaded
            async with factory() as other:
                ctx = await open_context(
                    other, await other.get(Campaign, campaign_id), dice, turn_id=None, seat_id=None
                )
                ctx.required_actions = [ref]
                loaded += 1
                if loaded == 2:
                    ready.set()
                await ready.wait()
                args = {
                    "character_id": hero,
                    "stat": "perception",
                    "target_id": "door",
                    "difficulty": "dc.easy",
                    "reason": "осмотр двери",
                    "action_ref": ref.model_dump(),
                }
                key = await bound_tool_key(ctx, "roll_check", args, f"call{index}")
                result = await execute(ctx, "roll_check", args, key=key)
                await other.commit()
                return result

        results = await asyncio.gather(worker(1), worker(2))
        assert results[0]["result"] == results[1]["result"]
        assert dice.queue == [18]
        assert sum(bool(r.get("repeated")) for r in results) == 1

    run(settings, concurrent)
