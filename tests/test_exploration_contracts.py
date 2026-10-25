import pytest
from pydantic import ValidationError

from app.rules.universal.exploration import (
    AbilityDefinitionV2,
    EffectIntentV2,
    IntentV2,
    definition_key,
    exploration_cost,
)


def definition(kind="cosmetic", **kwargs):
    return AbilityDefinitionV2(name="Искра", source="supernatural", effects=[EffectIntentV2(kind=kind)], **kwargs)


def test_supernatural_effects_are_paid_and_ordinary_checks_stay_free():
    assert exploration_cost(definition(), 1) == 1
    assert exploration_cost(definition(intensity="normal"), 1) == 3
    assert exploration_cost(definition(intensity="strong"), 1) == 12
    assert (
        exploration_cost(
            AbilityDefinitionV2(name="Слушать", source="mundane", effects=[EffectIntentV2(kind="observe")]), 1
        )
        == 0
    )


def test_semantic_identity_is_not_just_numeric_parameters_or_display_name():
    form, light = definition("change_form"), definition("illumination")
    assert definition_key(form) != definition_key(light)
    assert definition_key(form) == definition_key(form.model_copy(update={"name": "Красивый куст"}))
    renamed_effect = form.effects[0].model_copy(update={"label": "Зелёная листва", "target_id": "other"})
    assert definition_key(form) == definition_key(form.model_copy(update={"effects": [renamed_effect]}))


def test_permanent_object_is_a_paid_creation_not_an_infinite_buff():
    cup = AbilityDefinitionV2(
        name="Кружка", source="supernatural", effects=[EffectIntentV2(kind="create_object", lifetime="permanent")]
    )
    assert exploration_cost(cup, 1) == 1
    light = AbilityDefinitionV2(
        name="Светлячки",
        source="supernatural",
        duration_seconds=18,
        effects=[EffectIntentV2(kind="illumination", lifetime="timed")],
    )
    assert exploration_cost(light, 1) == 3
    assert exploration_cost(light, 10) == 30


def test_closed_supported_bounded_contracts_and_exact_counts():
    with pytest.raises(ValidationError):
        EffectIntentV2(kind="make_invincible")
    with pytest.raises(ValidationError):
        EffectIntentV2(kind="cosmetic", set_hp=100)
    with pytest.raises(ValidationError):
        EffectIntentV2(kind="create_object", capacity_ml=10**8)
    with pytest.raises(ValidationError):
        definition(duration_seconds=-1)
    with pytest.raises(ValidationError):
        definition(duration_seconds=1.5)
    with pytest.raises(ValidationError):
        IntentV2(schema_version=1, source="mundane")
    assert definition(duration_seconds="18").model_dump(mode="json")["duration_seconds"] == "18"


def test_no_free_magic_from_empty_or_nonnumeric_effect_lists():
    with pytest.raises(ValidationError):
        AbilityDefinitionV2(name="Пусто", source="supernatural", effects=[])
    assert exploration_cost(definition("speak"), 1) >= 1
