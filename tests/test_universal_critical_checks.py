import asyncio

import pytest

from app.core.universal.action_intents import ActionIntent
from app.core.universal.preparation import prepare_action
from app.core.universal.profiles import load_actor
from app.core.universal.resolution import ResolutionContext, resolve_action
from app.core.universal.rolls import ensure_roll_message
from app.rules.dice import FixedDice
from app.rules.universal.profiles import ResistanceSpec, resolve_check, resolve_resistance
from tests.test_universal_master import prepare
from tests.test_universal_resolution import setup


@pytest.mark.parametrize("natural, score, dc, success", [(20, 1, 40, True), (1, 100, 1, False)])
def test_natural_extremes_override_modifier_and_difficulty(natural, score, dc, success):
    result = resolve_check(FixedDice([natural]), score, False, dc)
    assert result.success is success
    assert result.critical is success
    assert result.critical_failure is not success


@pytest.mark.parametrize(
    "rolls, mode, critical, fumble",
    [
        ([1, 15], "advantage", False, False),
        ([20, 15], "disadvantage", False, False),
        ([4, 20], "advantage", True, False),
        ([1, 17], "disadvantage", False, True),
    ],
)
def test_only_selected_die_can_be_critical(rolls, mode, critical, fumble):
    result = resolve_check(FixedDice(rolls), 14, False, 12, mode)
    assert result.critical is critical
    assert result.critical_failure is fumble


def test_modified_total_is_not_a_natural_critical():
    assert not resolve_check(FixedDice([18]), 14, False, 12).critical  # total 20
    assert not resolve_check(FixedDice([3]), 6, False, 12).critical_failure  # total 1


@pytest.mark.parametrize("natural, score, dc, applied", [(20, 1, 40, False), (1, 100, 1, True)])
def test_resistance_uses_the_same_natural_extreme_rules(natural, score, dc, applied):
    result = resolve_resistance(
        FixedDice([natural]),
        "target",
        "effect",
        score,
        ResistanceSpec(attribute="wis", source_attribute="wis", difficulty=dc),
    )
    assert result.applied is applied


@pytest.mark.parametrize(
    "natural, branch, label", [(20, "critical_success", "crit_success"), (1, "critical_failure", "crit_fail")]
)
def test_critical_consequence_is_saved_displayed_and_replayed_once(tmp_path, natural, branch, label):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([natural]))
            compiled = await prepare_action(
                ctx,
                ActionIntent(
                    kind="ordinary_check",
                    difficulty=40 if natural == 20 else 1,
                    check_outcomes=dict(
                        success="Слышны шаги.",
                        failure="Звуки неразличимы.",
                        critical_success="Отчётливо слышны шаги из тоннеля впереди.",
                        critical_failure="Шорохи сбивают внимание: источник звука не удаётся определить.",
                    ),
                ),
                "critical",
            )
            result = await resolve_action(ctx, compiled.proposal, "critical")
            assert result.description == getattr(compiled.proposal.check_outcomes, branch)
            assert result.checks[0].critical is (natural == 20)
            assert result.checks[0].critical_failure is (natural == 1)
            card = await ensure_roll_message(s, "c", "game", None, "critical", ["seat"])
            assert card.data["outcome"] == label
            assert (await load_actor(s, "c", "hero"))[1].hp == 22  # Listening never gains an unrelated injury.
            replay = await resolve_action(
                ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([])), compiled.proposal, "critical"
            )
            assert replay.description == result.description
        await engine.dispose()

    asyncio.run(run())
