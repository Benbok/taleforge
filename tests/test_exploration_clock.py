import asyncio

from app.core.universal.clock import clock_view, complete_step
from app.core.universal.definitions import admit_definition, load_definition
from app.core.universal.effects import active_effects, dismiss_effect, start_effect
from app.db.models import Event
from app.rules.universal.exploration import AbilityDefinitionV2, EffectIntentV2
from tests.test_universal_resolution import setup


def test_casting_step_preserves_full_lifetime_and_replay_does_not_tick(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Event(id="cast-event", campaign_id="c", actor_id="hero", tool="universal_action", payload={}))
            await s.flush()
            effect = await start_effect(
                s,
                "c",
                "hero",
                "hero",
                "cast-event",
                "light",
                EffectIntentV2(kind="illumination", lifetime="timed"),
                6,
                18,
            )
            first = await complete_step(s, "c", "cast", 6)
            assert (await clock_view(s, "c"))["game_seconds"] == "6"
            assert (await active_effects(s, "c", "hero"))[0]["remaining_seconds"] == "18"
            assert (await complete_step(s, "c", "cast", 6)).id == first.id
            assert (await active_effects(s, "c", "hero"))[0]["remaining_seconds"] == "18"
            await complete_step(s, "c", "next", 6)
            assert (await active_effects(s, "c", "hero"))[0]["remaining_seconds"] == "12"
            await complete_step(s, "c", "wait", 12)
            assert not await active_effects(s, "c", "hero")
            assert effect.status == "expired"
        await engine.dispose()

    asyncio.run(run())


def test_clock_is_exact_and_reading_or_dismissal_never_advances_it(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            assert await clock_view(s, "c") == dict(game_seconds="0", step_index="0")
            await complete_step(s, "c", "long", 10**30)
            assert (await clock_view(s, "c"))["game_seconds"] == str(10**30)
            s.add(Event(id="event", campaign_id="c", actor_id="hero", tool="universal_action", payload={}))
            await s.flush()
            form = await start_effect(
                s, "c", "hero", "hero", "event", "form", EffectIntentV2(kind="change_form"), 10**30, 18
            )
            light = await start_effect(
                s, "c", "hero", "hero", "event", "light", EffectIntentV2(kind="illumination"), 10**30, 18
            )
            await dismiss_effect(s, "c", "hero", form.id)
            assert [e["id"] for e in await active_effects(s, "c", "hero")] == [light.id]
            assert (await clock_view(s, "c"))["game_seconds"] == str(10**30)
        await engine.dispose()

    asyncio.run(run())


def test_definitions_are_campaign_scoped_and_presentation_aliases_reuse_identity(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            definition = AbilityDefinitionV2(
                name="Куст", source="supernatural", effects=[EffectIntentV2(kind="change_form")]
            )
            first = await admit_definition(s, "c", definition)
            second = await admit_definition(s, "c", definition.model_copy(update={"name": "Зелёный куст"}))
            assert first.id == second.id and second.name == "Куст"
            assert (await load_definition(s, "c", first.id, 1)).id == first.id
            from app.core.campaigns import NotFound

            try:
                await load_definition(s, "foreign", first.id, 1)
            except NotFound:
                pass
            else:
                raise AssertionError("Foreign definition leaked")
        await engine.dispose()

    asyncio.run(run())


def test_concurrent_step_completion_advances_once(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)

        async def complete():
            async with maker() as s:
                step = await complete_step(s, "c", "same-source", 6)
                await s.commit()
                return step.id

        ids = await asyncio.gather(complete(), complete())
        assert ids[0] == ids[1]
        async with maker() as s:
            assert await clock_view(s, "c") == dict(game_seconds="6", step_index="1")
        await engine.dispose()

    asyncio.run(run())


def test_recasting_an_active_effect_renews_it_instead_of_stacking(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            for name in ("first", "second", "other"):
                s.add(Event(id=name, campaign_id="c", actor_id="hero", tool="universal_action", payload={}))
            await s.flush()
            light = EffectIntentV2(kind="illumination", lifetime="timed")
            first = await start_effect(s, "c", "hero", "hero", "first", "0", light, 0, 18)
            await complete_step(s, "c", "a", 6)
            assert (await active_effects(s, "c", "hero"))[0]["remaining_seconds"] == "12"
            second = await start_effect(s, "c", "hero", "hero", "second", "0", light, 12, 18)
            other = await start_effect(
                s, "c", "hero", "hero", "other", "0", EffectIntentV2(kind="camouflage", lifetime="timed"), 12, 18
            )
            await complete_step(s, "c", "b", 6)
            active = {e["id"]: e["remaining_seconds"] for e in await active_effects(s, "c", "hero")}
            assert active == {second.id: "18", other.id: "18"}
            await complete_step(s, "c", "c", 6)
            ids = [e["id"] for e in await active_effects(s, "c", "hero")]
            assert first.id not in ids and ids.count(second.id) == 1
        await engine.dispose()

    asyncio.run(run())
