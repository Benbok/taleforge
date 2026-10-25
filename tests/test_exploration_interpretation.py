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
                {"duration_seconds": 600},
                {"resolution": "check"},
            ]:
                with pytest.raises(ValueError):
                    await compile_exploration(ctx, base.model_copy(update=change), review, source)
            assert (await compile_exploration(ctx, base, review, source)).cost == 3
        await engine.dispose()

    asyncio.run(run())
