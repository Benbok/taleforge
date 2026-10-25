import asyncio

from app.core.universal.clock import complete_step
from app.core.universal.effects import start_effect
from app.db.models import Character, Event
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2
from tests.test_universal_resolution import setup, sheet


def test_periodic_damage_uses_one_saved_clock_and_skips_casting_step(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            event = Event(id="dot", campaign_id="c", actor_id="hero", tool="universal_action", payload={})
            s.add(event)
            await s.flush()
            effect = await start_effect(
                s,
                "c",
                "hero",
                "target",
                "dot",
                "dot",
                EffectIntentV2(kind="damage_over_time"),
                6,
                18,
                context={"intensity": "normal", "attribute": "wis", "source_sheet": sheet().model_dump(mode="json")},
            )
            await complete_step(s, "c", "cast", 6, dice=FixedDice([]))
            target = await s.get(Character, "target")
            assert target.resources["hp"] == "22"
            await complete_step(s, "c", "next", 6, dice=FixedDice([1]))
            assert target.resources["hp"] == "19"
            await complete_step(s, "c", "next", 6, dice=FixedDice([]))
            await complete_step(s, "c", "wait", 12, dice=FixedDice([1, 1]))
            assert target.resources["hp"] == "13" and effect.status == "expired"
            await complete_step(s, "c", "later", 6, dice=FixedDice([]))
            assert target.resources["hp"] == "13"
        await engine.dispose()

    asyncio.run(run())


def test_failure_between_periodic_ticks_rolls_back_health_and_time(tmp_path):
    import pytest

    from app.core.universal.clock import clock_view

    class BrokenDice:
        calls = 0

        def die(self, sides):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("crashed tick")
            return 1

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Event(id="dot", campaign_id="c", actor_id="hero", tool="universal_action", payload={}))
            await s.flush()
            await start_effect(
                s,
                "c",
                "hero",
                "target",
                "dot",
                "dot",
                EffectIntentV2(kind="damage_over_time"),
                0,
                18,
                context={"intensity": "normal", "attribute": "wis", "source_sheet": sheet().model_dump(mode="json")},
            )
            with pytest.raises(RuntimeError):
                await complete_step(s, "c", "wait", 12, dice=BrokenDice())
            assert (await s.get(Character, "target")).resources["hp"] == "22"
            assert (await clock_view(s, "c"))["game_seconds"] == "0"
            await complete_step(s, "c", "wait", 12, dice=FixedDice([1, 1]))
            assert (await s.get(Character, "target")).resources["hp"] == "16"
        await engine.dispose()

    asyncio.run(run())
