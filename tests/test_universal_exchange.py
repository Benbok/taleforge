import asyncio
from datetime import UTC

import pytest
from sqlalchemy import func, select

from app.core.universal.clock import clock_view
from app.core.universal.combat import run_exchange
from app.core.universal.resolution import ResolutionContext
from app.db.models import Entity, Event, UniversalStep
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2
from tests.test_exploration_resolution import prepare
from tests.test_universal_resolution import setup, sheet


async def enemy(s, hp="22"):
    row = Entity(
        id="foe",
        campaign_id="c",
        kind="creature",
        name="Страж",
        state={
            "hostile": True,
            "universal_sheet": sheet().model_dump(mode="json"),
            "resources": dict(hp=hp, energies=dict(str="18", dex="20", int="23", wis="24", cha="25")),
        },
    )
    s.add(row)
    await s.flush()
    return row


@pytest.mark.parametrize("kind", ["wait", "guard", "observe"])
def test_one_reply_and_one_completion_for_each_hero_action(tmp_path, kind):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20, 3, 3]))
            action = await prepare(s, ctx, kind, source="mundane")
            results = await run_exchange(ctx, action, request_key="m")
            assert len(results) == 2 and results[1].success
            assert (await clock_view(s, "c"))["game_seconds"] == "6"
            assert await s.scalar(select(func.count()).select_from(UniversalStep)) == 1
            assert (await run_exchange(ctx, action, request_key="m"))[0].status == "repeated"
            assert await s.scalar(select(func.count()).select_from(Event).where(Event.tool == "universal_action")) == 2
        await engine.dispose()

    asyncio.run(run())


def test_guard_applies_before_reply_without_losing_new_duration(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([14]))
            action = await prepare(s, ctx, "guard", source="mundane")
            result = await run_exchange(ctx, action, request_key="m")
            assert not result[1].success
            assert result[1].checks[0].difficulty == 14
            from app.core.universal.effects import active_effects

            assert (await active_effects(s, "c", "hero"))[0]["remaining_seconds"] == "6"
        await engine.dispose()

    asyncio.run(run())


def test_stale_chosen_enemy_is_rechecked_outside_model_transaction(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await prepare(s, ctx, "wait", source="mundane")

            async def choose(view):
                async with maker() as other:
                    foe = await other.get(Entity, "foe")
                    foe.state = {**foe.state, "resources": {**foe.state["resources"], "hp": "0"}}
                    await other.commit()
                return dict(actor_id="foe", target_id="hero")

            result = await run_exchange(ctx, action, choose_reply=choose, request_key="m")
            assert len(result) == 1
            assert (await clock_view(s, "c"))["game_seconds"] == "6"
        await engine.dispose()

    asyncio.run(run())


def test_restart_after_hero_commit_does_not_repeat_cast_or_selection(tmp_path):
    class Crash(BaseException):
        pass

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await prepare(s, ctx, "cosmetic")

            async def crash(view):
                raise Crash()

            with pytest.raises(Crash):
                await run_exchange(ctx, action, choose_reply=crash, request_key="m")
        async with maker() as s:
            ctx.session = s
            from datetime import datetime

            from app.db.models import CombatExchange

            exchange = await s.scalar(select(CombatExchange))
            exchange.selection_expires_at = datetime(2000, 1, 1, tzinfo=UTC)
            await s.commit()
            result = await run_exchange(ctx, action, choose_reply=crash, request_key="m")
            assert result[0].cost == 1
            assert await s.scalar(select(func.count()).select_from(Event).where(Event.tool == "universal_action")) == 1
            assert (await clock_view(s, "c"))["step_index"] == "1"
        await engine.dispose()

    asyncio.run(run())


def test_concurrent_duplicate_requests_produce_one_reply(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await prepare(s, ctx, "wait", source="mundane")
            await s.commit()

        async def invoke():
            async with maker() as s:
                ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20, 3, 3]))
                return await run_exchange(ctx, action, request_key="m")

        await asyncio.gather(invoke(), invoke())
        async with maker() as s:
            assert await s.scalar(select(func.count()).select_from(Event).where(Event.tool == "universal_action")) == 2
            assert (await clock_view(s, "c"))["step_index"] == "1"
        await engine.dispose()

    asyncio.run(run())


def test_hero_kills_foe_before_selection_and_no_reply_occurs(tmp_path):
    from tests.test_universal_combat_actions import attack

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s, hp="1")
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20, 4, 4]))
            action = await attack(s, ctx, [EffectIntentV2(kind="damage")], targets=["foe"])
            result = await run_exchange(ctx, action, request_key="attack")
            assert len(result) == 1
            assert (await clock_view(s, "c"))["step_index"] == "1"
        await engine.dispose()

    asyncio.run(run())
