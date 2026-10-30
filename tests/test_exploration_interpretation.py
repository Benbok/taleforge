import asyncio

import pytest

from app.core.universal.interpretation import compile_exploration, needs_intent_review, validate_exploration
from app.core.universal.resolution import ResolutionContext
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, IntentReview, IntentV2, RequirementV2
from tests.test_universal_resolution import setup


def test_semantic_coverage_blocks_weakened_magic_and_respects_pretending(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            intent = IntentV2(source="mundane", resolution="automatic", effects=[EffectIntentV2(kind="observe")])
            source = dict(source_message_id="m", source_text="кастую Куст, превращаюсь в куст", evidence="")
            assert needs_intent_review(source["source_text"], intent, False)
            with pytest.raises(ValueError):
                await compile_exploration(
                    ctx, intent, IntentReview(verdict="mismatch", message="Отсутствует превращение"), source
                )
            # The same keyword is not a deterministic magic classifier.
            pretend = {**source, "source_text": "делаю вид, что колдую"}
            action = await compile_exploration(ctx, intent, IntentReview(verdict="pass"), pretend)
            assert action.cost == 0 and action.definition.source == "mundane"
            magic = IntentV2(
                name="Куст",
                source="supernatural",
                resolution="automatic",
                intensity="light",
                requirements=[RequirementV2(id="form", quote="превращаюсь в куст", effect="change_form")],
                effects=[EffectIntentV2(kind="camouflage", required_by=["form"])],
            )
            with pytest.raises(ValueError):
                await compile_exploration(
                    ctx, magic, IntentReview(verdict="pass", covered_requirements=["form"]), source
                )
            magic.effects = [EffectIntentV2(kind="change_form", required_by=["form"])]
            action = await compile_exploration(
                ctx, magic, IntentReview(verdict="pass", covered_requirements=["form"]), source
            )
            assert action.cost == 3
            with pytest.raises(ValueError):
                await validate_exploration(ctx, action.model_copy(update={"cost": 0}))
            with pytest.raises(ValueError):
                await validate_exploration(
                    ctx, action.model_copy(update={"operations": [EffectIntentV2(kind="observe")]})
                )
        await engine.dispose()

    asyncio.run(run())


def test_closed_compiler_requires_real_targets_energy_and_complete_check_hints(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            base = IntentV2(
                source="supernatural",
                resolution="automatic",
                intensity="light",
                effects=[EffectIntentV2(kind="illumination")],
            )
            source = dict(source_message_id="m", source_text="свет", evidence="")
            review = IntentReview(verdict="pass")
            for change in [
                {"source": "mundane"},
                {"targets": ["foreign"]},
                {"resolution": "check"},
            ]:
                with pytest.raises(ValueError):
                    await compile_exploration(ctx, base.model_copy(update=change), review, source)
            assert (await compile_exploration(ctx, base, review, source)).cost == 3
        await engine.dispose()

    asyncio.run(run())


def test_a_term_is_eighteen_seconds_unless_the_player_names_another(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            source = dict(source_message_id="m", source_text="превращаюсь в куст", evidence="")
            review = IntentReview(verdict="pass", covered_requirements=["form"])

            def magic(**extra):
                return IntentV2(
                    name="Куст",
                    source="supernatural",
                    resolution="automatic",
                    intensity="light",
                    requirements=[RequirementV2(id="form", quote="превращаюсь в куст", effect="change_form")],
                    effects=[EffectIntentV2(kind="change_form", required_by=["form"])],
                    **extra,
                )

            plain = await compile_exploration(ctx, magic(), review, source)
            assert plain.definition.duration_seconds == 18 and plain.cost == 3
            named = await compile_exploration(ctx, magic(duration_seconds=36), review, source)
            assert named.definition.duration_seconds == 36 and named.cost == 6  # six units instead of three
        await engine.dispose()

    asyncio.run(run())


def test_an_altered_form_does_not_make_the_code_refuse_actions(tmp_path):
    """What a form allows is for the world's laws and the master to say; the engine only counts and executes."""
    from app.core.universal.effects import start_effect
    from app.db.models import Event

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Event(id="form", campaign_id="c", actor_id="hero", tool="universal_action", payload={}))
            await s.flush()
            await start_effect(
                s, "c", "hero", "hero", "form", "0", EffectIntentV2(kind="change_form", lifetime="timed"), 0, 18
            )
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            source = dict(source_message_id="m", source_text="я иду к выходу", evidence="")
            walking = IntentV2(source="mundane", resolution="automatic", effects=[EffectIntentV2(kind="move")])
            action = await compile_exploration(ctx, walking, IntentReview(verdict="pass"), source)
            assert [op.kind for op in action.operations] == ["move"]
        await engine.dispose()

    asyncio.run(run())


def test_a_stray_known_reference_never_blocks_an_ordinary_action_and_is_explained_for_spells(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            source = dict(source_message_id="m", source_text="жду и наблюдаю", evidence="")
            watching = IntentV2(
                source="mundane",
                player_request="ordinary",
                resolution="automatic",
                known_profile_id="ability2-not-mine",
                effects=[EffectIntentV2(kind="observe")],
            )
            action = await compile_exploration(ctx, watching, IntentReview(verdict="pass"), source)
            assert action.cost == 0 and action.definition.source == "mundane"
            spell = watching.model_copy(
                update=dict(source="supernatural", effects=[EffectIntentV2(kind="cosmetic")], intensity="light")
            )
            with pytest.raises(ValueError, match="known_profile_id"):
                await compile_exploration(ctx, spell, IntentReview(verdict="pass"), source)
        await engine.dispose()

    asyncio.run(run())


def test_a_rejected_requirement_says_what_to_fix(tmp_path):
    """The repair message is all the model sees on its second try: it must name the cause and the player's words."""

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            source = dict(source_message_id="m", source_text="захожу в постоялый двор", evidence="")
            review = IntentReview(verdict="pass", covered_requirements=["r"])

            def intent(quote, kind):
                return IntentV2(
                    source="mundane",
                    player_request="ordinary",
                    resolution="automatic",
                    requirements=[RequirementV2(id="r", quote=quote, effect="move")],
                    effects=[EffectIntentV2(kind=kind, required_by=["r"])],
                )

            # a quote from the narration instead of the player's own words
            with pytest.raises(ValueError, match="захожу в постоялый двор") as wrong_quote:
                await compile_exploration(ctx, intent("Что ты сделаешь, Пупкин", "move"), review, source)
            assert "дословн" in str(wrong_quote.value)
            # the quote is right but no effect of the claimed kind carries it
            with pytest.raises(ValueError, match="move") as no_effect:
                await compile_exploration(ctx, intent("захожу в постоялый двор", "observe"), review, source)
            assert "effects" in str(no_effect.value)
        await engine.dispose()

    asyncio.run(run())
