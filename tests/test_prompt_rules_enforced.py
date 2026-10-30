import asyncio

import pytest
from pydantic import ValidationError

from app.core.universal.interpretation import compile_exploration
from app.core.universal.resolution import ResolutionContext
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, IntentReview, IntentV2, RequirementV2
from tests.test_universal_resolution import setup


@pytest.mark.parametrize(
    "operation, message",
    [
        ({"kind": "move", "destination_id": "foreign", "travel_scope": "between_locations"}, "known_exits"),
        ({"kind": "move", "destination_id": "hall"}, "travel_scope"),
    ],
)
def test_movement_rejection_names_the_repair(tmp_path, operation, message):
    async def run():
        engine, maker = await setup(tmp_path)
        try:
            async with maker() as session:
                ctx = ResolutionContext(session, "c", "u", "seat", "hero", FixedDice([]))
                intent = IntentV2(source="mundane", resolution="automatic", effects=[EffectIntentV2(**operation)])
                with pytest.raises(ValueError, match=message):
                    await compile_exploration(
                        ctx,
                        intent,
                        IntentReview(verdict="pass"),
                        {
                            "source_message_id": "m",
                            "source_text": "иду в зал",
                            "world_development": True,
                            "known_exits": [{"id": "hall", "state": "open"}],
                        },
                    )
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_quote_rejection_names_the_players_words(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        try:
            async with maker() as session:
                ctx = ResolutionContext(session, "c", "u", "seat", "hero", FixedDice([]))
                intent = IntentV2(
                    source="mundane",
                    resolution="automatic",
                    requirements=[RequirementV2(id="r", quote="не мои слова", effect="wait")],
                    effects=[EffectIntentV2(kind="wait", required_by=["r"])],
                )
                with pytest.raises(ValueError, match="дословным фрагментом слов игрока"):
                    await compile_exploration(
                        ctx,
                        intent,
                        IntentReview(verdict="pass", covered_requirements=["r"]),
                        {
                            "source_message_id": "m",
                            "source_text": "жду",
                        },
                    )
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("difficulty", [0, 41])
def test_difficulty_is_bounded_by_the_schema(difficulty):
    with pytest.raises(ValidationError, match="difficulty"):
        IntentV2(source="mundane", difficulty=difficulty, effects=[EffectIntentV2(kind="wait")])


def test_vessel_capacity_is_bounded_by_the_schema():
    with pytest.raises(ValidationError, match="capacity_ml"):
        EffectIntentV2(kind="create_object", capacity_ml=2001)
