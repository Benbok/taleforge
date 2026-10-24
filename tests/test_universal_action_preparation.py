import asyncio

import pytest
from sqlalchemy import select

from app.core.universal.contracts import ResolutionContext
from app.db.models import RuntimeProfile
from app.rules.dice import FixedDice
from tests.test_universal_resolution import setup


@pytest.mark.parametrize(
    "intent,category,cost",
    [
        (dict(kind="ordinary_check", attribute="dex", name="Факел"), "ordinary_check", 0),
        (dict(kind="ability", attribute="wis", effect="check", name="Зрение лозы"), "ability", 3),
        (
            dict(kind="ability", profile=dict(id="torch", kind="check", attribute="dex"), reason="Факел"),
            "ordinary_check",
            0,
        ),
    ],
)
def test_semantic_and_saved_legacy_actions_compile_into_server_profiles(tmp_path, intent, category, cost):
    from app.core.universal.action_intents import parse_intent
    from app.core.universal.preparation import prepare_action
    from app.rules.universal.profiles import resource_cost

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            compiled = await prepare_action(
                ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([])), parse_intent(intent), "source"
            )
            assert compiled.category == category
            assert compiled.proposal.targets == ["hero"]
            assert resource_cost(compiled.proposal.profile, 1) == cost
            assert len(list(await s.scalars(select(RuntimeProfile)))) == 1
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "intent,code",
    [
        (
            dict(kind="ability", attribute="wis", effect="narrative", duration=3, clock="turn", target_scope="scene"),
            "unsupported_duration",
        ),
        (dict(kind="ability", attribute="wis", effect="check", targets=["environment"]), "target_unavailable"),
        (dict(kind="ability", known_profile_id="another-heros-ability"), "not_allowed"),
    ],
)
def test_invalid_preparation_never_saves_executable_profile(tmp_path, intent, code):
    from app.core.universal.action_intents import parse_intent
    from app.core.universal.preparation import prepare_action
    from app.rules.universal.failures import ActionValidationError

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            with pytest.raises(ActionValidationError) as error:
                await prepare_action(
                    ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([])), parse_intent(intent), "source"
                )
            assert error.value.failure.code == code
            assert not list(await s.scalars(select(RuntimeProfile)))
        await engine.dispose()

    asyncio.run(run())
