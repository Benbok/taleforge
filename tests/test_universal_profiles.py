from fractions import Fraction

import pytest
from pydantic import ValidationError

from app.rules.dice import FixedDice
from app.rules.universal import profiles as rules
from app.rules.universal.contracts import AbilityScores, HeroDescription, UniversalSheet


def sheet(level=1, score=14):
    return UniversalSheet(
        level=level,
        abilities=AbilityScores(str=14, dex=14, con=14, int=14, wis=score, cha=14),
        description=HeroDescription(identity="mage"),
    )


def profile(**changes):
    return rules.ProfileSpec(**{"id": "bolt", "revision": 1, "attribute": "wis", "kind": "damage", **changes})


def test_normal_damage_and_cost_follow_level_without_multiplying_attribute():
    for level, expected, cost in [(1, 6, 3), (10, 24, 30)]:
        result = rules.resolve_attack(FixedDice([10, 4]), sheet(level), 12, profile())
        assert result.success and result.damage == expected and result.cost == cost


def test_critical_doubles_only_base_dice_and_immunity_stays_zero():
    p = profile(item_id="wand", rarity="rare", damage_bonus=1)
    result = rules.resolve_attack(FixedDice([20, 4, 3]), sheet(10), 999, p)
    assert result.critical and result.damage == 28
    assert rules.resolve_attack(FixedDice([20, 4, 3]), sheet(10), 999, p, immune=True).damage == 0
    assert rules.resolve_attack(FixedDice([1]), sheet(), -999, profile()).critical_failure


def test_resistance_examples_have_exact_binding_probabilities_and_no_training():
    spec = rules.bind_resistance(rules.ResistanceSpec(source_attribute="wis", attribute="dex"), 33)
    assert spec.difficulty == 21
    for score, count in [(14, 18), (24, 13), (33, 9)]:
        outcomes = [rules.resolve_resistance(FixedDice([die]), "enemy", "vine", score, spec) for die in range(1, 21)]
        assert sum(x.applied for x in outcomes) == count
        assert outcomes[-1].total == 20 + (score - 10) // 2
    assert rules.resolve_resistance(FixedDice([20]), "enemy", "vine", 1, spec).applied


def test_checks_use_trained_and_edge_but_do_not_inherit_attack_autosuccess():
    assert rules.resolve_check(FixedDice([10]), 14, True, 14, "normal").success
    assert rules.resolve_check(FixedDice([2, 17]), 14, False, 19, "advantage").success
    assert not rules.resolve_check(FixedDice([2, 17]), 14, False, 19, "disadvantage").success
    assert not rules.resolve_check(FixedDice([20]), 14, False, 99, "normal").success


def test_cost_prices_intensity_targets_duration_and_components():
    extra = rules.EffectSpec(id="bind", kind="cannot_move")
    assert [rules.resource_cost(profile(intensity=q), 10) for q in ["light", "normal", "strong"]] == [10, 30, 120]
    assert rules.resource_cost(profile(target_count=2, duration=3, effects=[extra]), 10) == 360
    assert rules.resource_cost(profile(use_kind="weapon_basic", attribute="str"), 10) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"base_dice": "100d100"},
        {"base_dice": "1d8"},
        {"attack_bonus": 999},
        {"rarity": "rare"},
        {"intensity": "strong", "use_kind": "weapon_basic"},
        {"effects": [dict(id="free", kind="heal", value=999)]},
        {"kind": "narrative", "effects": [dict(id="free", kind="defense_bonus", value=1)]},
        {"target_count": True},
        {"duration": 1.5},
        {"level": 10},
    ],
)
def test_profile_rejects_unbounded_or_free_power(changes):
    with pytest.raises(ValidationError):
        profile(**changes)


def test_numeric_effects_must_fit_intensity_budget_and_controls_are_specific():
    with pytest.raises(ValidationError):
        profile(effects=[dict(id="buff", kind="check_bonus", value=3)])
    with pytest.raises(ValidationError):
        rules.ProfileSpec(id="control", revision=1, attribute="wis", kind="control")
    control = rules.ProfileSpec(
        id="control",
        revision=1,
        attribute="wis",
        kind="control",
        effects=[rules.EffectSpec(id="bind", kind="cannot_move")],
    )
    assert rules.numeric_component_count(control) == 1
    assert rules.resource_cost(control, 1) == 3


def test_rarity_is_exact_and_flat_bonus_does_not_double_apply_status():
    assert rules.RARITY_MULTIPLIERS == {
        "common": Fraction(1),
        "rare": Fraction(5, 4),
        "unique": Fraction(3, 2),
        "epic": Fraction(2),
    }
    assert rules.damage_amount(FixedDice([4]), sheet(), profile(item_id="wand", rarity="rare")) == 7
    assert rules.damage_amount(FixedDice([4]), sheet(), profile(item_id="wand", rarity="rare", damage_bonus=1)) == 7


def test_large_numbers_serialize_as_decimal_strings_and_restore_is_capped():
    level = 10**80
    p = profile()
    outcome = rules.resolve_attack(FixedDice([20, 4, 4]), sheet(level), 12, p)
    assert outcome.damage == 2 * level + 8
    assert outcome.model_dump(mode="json")["damage"] == str(2 * level + 8)
    assert outcome.model_dump(mode="json")["natural"] == 20
    assert rules.resource_cost(p, level) == 3 * level
    assert rules.restore(2, 10, 99) == 10
    assert rules.restore(2, 10**100, 10**90) == 2 + 10**90
    with pytest.raises(ValueError):
        rules.restore(11, 10, 1)
    with pytest.raises(ValueError):
        rules.resolve_resistance(
            FixedDice([10]), "t", "e", 14, rules.ResistanceSpec(source_attribute="wis", attribute="dex")
        )


def test_check_profiles_price_magical_work_without_giving_free_extra_power():
    mundane = rules.ProfileSpec(id="look", attribute="int", kind="check")
    magical = rules.ProfileSpec(id="scry", attribute="wis", kind="check", resource_key="wis")
    assert rules.resource_cost(mundane, 10) == 0
    assert rules.resource_cost(magical, 10) == 30
    with pytest.raises(ValidationError):
        rules.ProfileSpec(id="free", attribute="int", kind="check", intensity="strong")
    with pytest.raises(ValidationError):
        rules.ProfileSpec(id="free", attribute="int", kind="check", effects=[dict(id="bind", kind="cannot_move")])


def test_realized_damage_values_are_supported_but_never_accepted_as_profile_templates():
    effect = rules.EffectSpec(id="hit", kind="damage", value=24)
    outcome = rules.ActionOutcome(success=True, public_effects=[effect])
    assert outcome.model_dump(mode="json")["public_effects"][0]["value"] == "24"
    with pytest.raises(ValidationError):
        profile(effects=[effect])
