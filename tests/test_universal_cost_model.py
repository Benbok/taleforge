"""Who pays for what: magic pays Wisdom, a thing made from improvised means pays Intelligence, and any other tested
deed pays its own ability a point for every point of difficulty over ten."""

import pytest

from app.rules.universal.exploration import (
    AbilityDefinitionV2,
    EffectIntentV2,
    clean_model_intent,
    energy_attribute,
    exploration_cost,
)


def definition(source, attribute, *effects):
    return AbilityDefinitionV2(
        name="Дело", source=source, attribute=attribute, effects=list(effects) or [EffectIntentV2(kind="wait")]
    )


def made(**extra):
    return EffectIntentV2(kind="create_object", template="structure", scale="small", **extra)


@pytest.mark.parametrize("attribute", ["int", "cha", "str"])
def test_magic_always_draws_wisdom_whatever_it_tests(attribute):
    spell = definition("supernatural", attribute, EffectIntentV2(kind="illumination"))
    assert energy_attribute(spell) == "wis"


def test_making_a_thing_from_improvised_means_draws_intelligence_at_the_price_of_its_size():
    deed = definition("mundane", "dex", made())
    assert energy_attribute(deed) == "int"
    magic = definition("supernatural", "wis", made())
    assert exploration_cost(deed, 1) == exploration_cost(magic, 1) > 0


@pytest.mark.parametrize("difficulty,price", [(8, 0), (10, 0), (11, 1), (15, 5), (20, 10)])
def test_a_tested_deed_costs_its_ability_by_the_difficulty(difficulty, price):
    deed = definition("mundane", "str")
    assert energy_attribute(deed) == "str"
    assert exploration_cost(deed, 1, difficulty, "check") == price


def test_what_is_not_tested_is_free_and_so_is_the_body():
    assert exploration_cost(definition("mundane", "dex"), 1, 20, "automatic") == 0
    assert exploration_cost(definition("mundane", "dex"), 1, 20, "attack") == 0
    assert exploration_cost(definition("mundane", "con"), 1, 20, "check") == 0


def raw(claim):
    return dict(
        source="mundane",
        player_request=claim,
        attribute="int",
        effects=[dict(kind="create_object", template="structure", scale="small")],
    )


def test_an_ordinary_deed_may_make_a_thing_but_pretended_magic_makes_nothing():
    assert [e["kind"] for e in clean_model_intent(raw("ordinary"))["effects"]] == ["create_object"]
    assert [e["kind"] for e in clean_model_intent(raw("pretend"))["effects"]] == ["wait"]
