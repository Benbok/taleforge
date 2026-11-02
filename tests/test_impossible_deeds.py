"""What no hand could do is refused before anything is rolled or spent: no lucky die carries a hero over a city."""

import asyncio

import pytest

from app.core.universal.resolution import ResolutionContext
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2
from app.rules.universal.failures import ActionValidationError
from tests.test_universal_mundane_feats import attempt
from tests.test_universal_resolution import setup


def test_an_impossible_deed_is_refused_without_a_roll_or_cost(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20]))
            with pytest.raises(ActionValidationError) as caught:
                await attempt(s, ctx, "str", "перепрыгиваю через город", EffectIntentV2(kind="move"), 30)
            assert caught.value.failure.code == "impossible_deed"
        await engine.dispose()

    asyncio.run(run())
