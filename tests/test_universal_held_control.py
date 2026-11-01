"""Control that holds: no timer, the held one tries to break free every turn, the holder falling frees them."""

import asyncio

import pytest

from app.core.universal.clock import complete_step
from app.core.universal.control import HOLD_SECONDS
from app.core.universal.effects import active_effects, start_effect
from app.db.models import Character, Event
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2
from tests.test_universal_exchange import enemy
from tests.test_universal_resolution import setup


async def hold(s, kind="cannot_act", resist="con", dc=12, from_sequence=1, source="hero"):
    s.add(Event(id="grip", campaign_id="c", actor_id=source, tool="universal_action", payload={}))
    await s.flush()
    return await start_effect(
        s,
        "c",
        source,
        "foe",
        "grip",
        "0",
        EffectIntentV2(kind=kind, lifetime="timed"),
        0,
        HOLD_SECONDS,
        context=dict(held=True, resist=resist, break_dc=dc, from_sequence=from_sequence),
    )


async def kinds(s):
    return [e["kind"] for e in await active_effects(s, "c", "foe")]


def test_a_hold_has_no_timer_and_the_first_turn_is_never_a_try(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            await hold(s, from_sequence=1)
            # the turn the hold was put on is not a try, and an hour later it still holds when the tries fail
            await complete_step(s, "c", "first", 6, dice=FixedDice([20]))
            assert await kinds(s) == ["cannot_act"]
            await complete_step(s, "c", "hour", 3600, dice=FixedDice([2]))
            assert await kinds(s) == ["cannot_act"]
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("roll,freed", [(5, False), (10, False), (11, True), (19, True)])
def test_the_held_one_breaks_free_when_the_roll_meets_the_difficulty(tmp_path, roll, freed):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            await hold(s, dc=12, resist="con", from_sequence=0)  # the foe's con is 12: a modifier of +1
            step = await complete_step(s, "c", "try", 6, dice=FixedDice([roll]))
            assert (await kinds(s) == []) is freed
            assert any(c["kind"] == "effect_released" for c in step.changes) is freed
        await engine.dispose()

    asyncio.run(run())


def test_the_hold_ends_when_the_holder_falls(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            await hold(s, dc=40, from_sequence=0)
            hero = await s.get(Character, "hero")
            hero.resources = {
                **hero.resources,
                "hp": "0",
                "vitality": dict(state="unconscious", successes="0", failures="0", eligible_sequence="99"),
            }
            await s.flush()
            await complete_step(s, "c", "fall", 6, dice=FixedDice([1]))
            assert await kinds(s) == []  # nobody holds the foe any more, whatever the dice said
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["cannot_move", "cannot_act", "cannot_target"])
def test_an_ordinary_deed_may_hold_a_foe_too(tmp_path, kind):
    """Found in play: tying a demon with a rope, a trip, a blow to the nape were narrated and held nothing, because
    control was kept for abilities only."""
    from app.core.universal.interpretation import compile_exploration
    from app.db.models import Message
    from app.rules.universal.exploration import IntentReview, IntentV2, clean_model_intent

    raw = dict(
        source="mundane",
        resolution="check",
        attribute="str",
        difficulty=12,
        targets=["foe"],
        effects=[dict(kind=kind, target_id="foe", lifetime="timed", resistance_attribute="dex")],
        check_outcomes=dict(
            success="Держит.", failure="Вырвался.", critical_success="Держит крепко.", critical_failure="Упал."
        ),
    )
    assert clean_model_intent(dict(raw))["effects"][0]["kind"] == kind  # not stripped as "magic"

    async def run():
        from app.core.universal.resolution import ResolutionContext

        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            s.add(
                Message(
                    id="m", campaign_id="c", seq=1, seat_id="seat", author_user_id="u", kind="action", content="Вяжу"
                )
            )
            await s.flush()
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            intent = IntentV2.model_validate(
                {**clean_model_intent(dict(raw)), "requirements": [dict(id="r", quote="Вяжу", effect=kind)]}
            )
            intent.effects[0] = intent.effects[0].model_copy(update={"required_by": ["r"]})
            action = await compile_exploration(
                ctx,
                intent,
                IntentReview(verdict="pass", covered_requirements=["r"]),
                dict(source_message_id="m", source_text="Вяжу", evidence=""),
            )
            assert action.definition.source == "mundane" and action.cost == 2  # the difficulty of 12 costs two
        await engine.dispose()

    asyncio.run(run())


def test_the_scene_says_what_a_creature_is_held_from(tmp_path):
    from app.core.campaigns import Viewer
    from app.core.universal.scene import universal_scene
    from app.db.models import Campaign, Scene, Seat, User

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            await hold(s, kind="cannot_act", from_sequence=1)
            s.add(Scene(campaign_id="c", mode="combat"))
            await s.flush()
            viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "seat"))
            scene = await universal_scene(s, viewer.campaign, viewer)
            assert {row["id"]: row.get("held") for row in scene["entities"]}["foe"] == ["cannot_act"]
        await engine.dispose()

    asyncio.run(run())
