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


def test_a_created_object_is_a_paid_timed_creation_not_an_infinite_buff():
    cup = AbilityDefinitionV2(
        name="Кружка", source="supernatural", effects=[EffectIntentV2(kind="create_object", lifetime="timed")]
    )
    assert exploration_cost(cup, 1) == 3
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


def test_camouflage_is_part_of_the_form_and_not_charged_twice():
    def spell(*kinds):
        return AbilityDefinitionV2(
            name="Куст",
            source="supernatural",
            intensity="normal",
            duration_seconds=18,
            effects=[
                EffectIntentV2(kind=kind, **({"form": "plant_bush"} if kind == "change_form" else {})) for kind in kinds
            ],
        )

    assert exploration_cost(spell("change_form"), 1) == 9
    assert exploration_cost(spell("change_form", "camouflage"), 1) == 9
    assert exploration_cost(spell("camouflage"), 1) == 9  # on its own it is still a paid effect
    assert exploration_cost(spell("change_form", "illumination"), 1) == 18


def test_model_filler_for_unrelated_effect_fields_is_dropped_before_validation():
    from app.rules.universal.exploration import clean_model_intent

    def parsed(*effects, **top):
        return IntentV2.model_validate(
            clean_model_intent(
                {"schema_version": 2, "source": "mundane", "resolution": "automatic", **top, "effects": list(effects)}
            )
        )

    cup = parsed(
        {"kind": "create_object", "template": "vessel", "material": "wood", "form": "vessel", "lifetime": "permanent"}
    )
    assert cup.effects[0].lifetime == "timed" and cup.effects[0].material == "wood"  # relevant fields stay
    fill = parsed(
        {
            "kind": "fill",
            "amount": "200",
            "form": "vessel",
            "material": "stone",
            "lifetime": "permanent",
            "target_id": None,
        }
    )
    assert fill.effects[0].lifetime == "instant" and fill.effects[0].amount == 200
    bush = parsed({"kind": "change_form", "form": "plant_bush", "template": "vessel"})
    assert bush.effects[0].form == "plant_bush"
    assert parsed({"kind": "observe", "aspect": "hearing", "form": "vessel"}).effects[0].aspect == "hearing"
    assert parsed({"kind": "move"}, targets=["loc1"]).targets == []  # stage 2A acts on the hero alone
    with pytest.raises(ValidationError):  # a wrong value in a field that does matter is still refused
        parsed({"kind": "change_form", "form": "vessel"})
    with pytest.raises(ValidationError):  # unknown fields are not silently swallowed
        parsed({"kind": "move", "invented": 1})


def test_obvious_slips_in_the_models_own_bookkeeping_are_mended_without_changing_meaning():
    from app.rules.universal.exploration import clean_model_intent

    def base(**top):
        return {"schema_version": 2, "source": "supernatural", "resolution": "automatic", **top}

    # a requirement the model forgot to link to the effect of the same kind
    unlinked = clean_model_intent(
        base(
            requirements=[{"id": "r1", "quote": "свет", "effect": "illumination"}],
            effects=[{"kind": "illumination", "required_by": []}],
        )
    )
    assert unlinked["effects"][0]["required_by"] == ["r1"]
    # no effect of that kind exists: the gap is real and stays for the server to refuse
    gap = clean_model_intent(
        base(requirements=[{"id": "r1", "quote": "x", "effect": "heal"}], effects=[{"kind": "cosmetic"}])
    )
    assert not gap["effects"][0].get("required_by")
    # duplicate requirement ids and links to nothing
    twin = clean_model_intent(
        base(
            requirements=[
                {"id": "ch_1", "quote": "куст", "effect": "change_form"},
                {"id": "ch_1", "quote": "тень", "effect": "camouflage"},
            ],
            effects=[
                {"kind": "change_form", "required_by": ["ch_1", "ghost"]},
                {"kind": "camouflage", "required_by": []},
            ],
        )
    )
    ids = [r["id"] for r in twin["requirements"]]
    assert len(set(ids)) == 2 and "ghost" not in twin["effects"][0]["required_by"]
    assert twin["effects"][1]["required_by"] == [ids[1]]
    # an ordinary action with nothing mechanical in it still passes as waiting
    assert clean_model_intent(base(source="mundane", effects=[]))["effects"] == [{"kind": "wait"}]
    assert clean_model_intent(base(effects=[]))["effects"] == []  # a spell with no effect is not invented
    # pretending is acting, not magic; a claimed spell keeps its magic for the review to weigh
    pretend = clean_model_intent(base(source="mundane", player_request="pretend", effects=[{"kind": "cosmetic"}]))
    assert pretend["effects"] == [{"kind": "wait"}]
    claimed = clean_model_intent(base(source="mundane", player_request="supernatural", effects=[{"kind": "cosmetic"}]))
    assert claimed["effects"][0]["kind"] == "cosmetic"
    # where the hero walks, places or looks is the story's business, not a target of the effect
    walking = clean_model_intent(base(source="mundane", effects=[{"kind": "move", "target_id": "loc1"}]))
    assert "target_id" not in walking["effects"][0]
    pouring = clean_model_intent(base(source="mundane", effects=[{"kind": "pour", "target_id": "ob_cup"}]))
    assert pouring["effects"][0]["target_id"] == "ob_cup"  # for pouring it is the vessel


def test_null_spelled_as_text_and_a_made_up_name_for_the_object_being_created_are_dropped():
    from app.rules.universal.exploration import clean_model_intent

    seen = clean_model_intent(
        {
            "schema_version": 2,
            "source": "mundane",
            "effects": [{"kind": "observe", "object_id": "null", "label": "None"}],
        }
    )
    assert "object_id" not in seen["effects"][0] and "label" not in seen["effects"][0]
    made = clean_model_intent(
        {"schema_version": 2, "source": "supernatural", "effects": [{"kind": "create_object", "object_id": "mug_1"}]}
    )
    assert "object_id" not in made["effects"][0]  # the cup is the result of this effect, not a thing to point at


def test_a_zero_amount_means_the_amount_was_not_given():
    from app.rules.universal.exploration import clean_model_intent

    drink = clean_model_intent(
        {"schema_version": 2, "source": "mundane", "effects": [{"kind": "consume", "amount": "0"}]}
    )
    assert "amount" not in drink["effects"][0]
    assert IntentV2.model_validate(drink).effects[0].amount == 300
    kept = clean_model_intent(
        {"schema_version": 2, "source": "mundane", "effects": [{"kind": "consume", "amount": "50"}]}
    )
    assert kept["effects"][0]["amount"] == "50"


def test_acts_with_no_uncertain_outcome_never_need_a_roll_and_numbers_are_made_exact():
    from app.rules.universal.exploration import clean_model_intent

    def base(kind, **top):
        return {"schema_version": 2, "source": "mundane", "resolution": "check", "effects": [{"kind": kind}], **top}

    for kind in ("move", "speak", "wait", "hold_breath"):
        assert clean_model_intent(base(kind))["resolution"] == "automatic"
    assert clean_model_intent(base("observe"))["resolution"] == "check"  # a search may be a real risk
    assert clean_model_intent(base("move", source="supernatural"))["resolution"] == "check"
    assert clean_model_intent(base("move", elapsed_game_seconds=6.0))["elapsed_game_seconds"] == "6"
    assert clean_model_intent(base("move", elapsed_game_seconds="12.0"))["elapsed_game_seconds"] == "12"
    assert "elapsed_game_seconds" not in clean_model_intent(
        base("move", elapsed_game_seconds=2.5)
    )  # the default applies


def creation(scale=None, *, sturdiness=None, lifetime="timed", **extra):
    fields = {"kind": "create_object", "template": "structure", "lifetime": lifetime, **extra}
    if scale:
        fields["scale"] = scale
    if sturdiness:
        fields["sturdiness"] = sturdiness
    return AbilityDefinitionV2(name="Создание", source="supernatural", effects=[EffectIntentV2(**fields)])


def test_creation_price_follows_the_models_scale_and_sturdiness():
    prices = {s: exploration_cost(creation(s), 1) for s in ("tiny", "small", "medium", "large", "huge")}
    assert prices == {"tiny": 3, "small": 6, "medium": 12, "large": 24, "huge": 48}  # 1, 2, 4, 8, 16 per unit, 3 units
    assert exploration_cost(creation("large", sturdiness="sturdy"), 1) == 48
    assert exploration_cost(creation("large", sturdiness="fragile"), 1) == 24
    assert exploration_cost(creation("huge"), 2) == 96
    cup = AbilityDefinitionV2(name="Кружка", source="supernatural", effects=[EffectIntentV2(kind="create_object")])
    assert exploration_cost(cup, 1) == 3  # a creation with no stated scale is the old cup


def test_leads_to_is_for_large_creations_only():
    with pytest.raises(ValidationError):
        creation("small", leads_to="Другой берег")
    assert creation("large", leads_to="Другой берег", leads_view="Тёмный уступ").effects[0].leads_to == "Другой берег"
    assert creation("huge", leads_to="Другой берег").effects[0].scale == "huge"


def test_scale_and_sturdiness_change_the_identity_of_a_creation_but_a_label_does_not():
    assert definition_key(creation("tiny")) != definition_key(creation("huge"))
    assert definition_key(creation("large")) != definition_key(creation("large", sturdiness="sturdy"))
    assert definition_key(creation("large", label="Мост")) == definition_key(creation("large", label="Переправа"))
    cup = AbilityDefinitionV2(
        name="Кружка", source="supernatural", effects=[EffectIntentV2(kind="create_object", lifetime="timed")]
    )
    assert definition_key(cup).startswith("ability2-")  # defaults stay out of the key, so a learned cup keeps its id


def test_the_tolerant_parser_keeps_the_scale_and_drops_a_destination_a_small_creation_cannot_have():
    from app.rules.universal.exploration import clean_model_intent

    raw = {
        "schema_version": 2,
        "source": "supernatural",
        "effects": [
            {"kind": "create_object", "template": "structure", "scale": "small", "leads_to": "Берег", "form": "vessel"}
        ],
    }
    effect = clean_model_intent(raw)["effects"][0]
    assert effect["scale"] == "small" and "leads_to" not in effect and "form" not in effect
    big = clean_model_intent({**raw, "effects": [{**raw["effects"][0], "scale": "huge"}]})["effects"][0]
    assert big["leads_to"] == "Берег"


def test_a_walk_over_a_remembered_structure_keeps_its_check_while_plain_walking_does_not():
    from app.rules.universal.exploration import clean_model_intent

    def walking(**effect):
        return clean_model_intent(
            {"schema_version": 2, "source": "mundane", "resolution": "check", "effects": [{"kind": "move", **effect}]}
        )

    assert walking()["resolution"] == "automatic"
    assert walking(object_id="en_bridge")["resolution"] == "check"


def test_pretending_to_cast_is_ordinary_acting_even_when_the_model_labels_it_supernatural():
    from app.rules.universal.exploration import clean_model_intent

    pretend = clean_model_intent(
        {
            "schema_version": 2,
            "source": "supernatural",
            "player_request": "pretend",
            "effects": [{"kind": "cosmetic"}],
        }
    )
    assert pretend["source"] == "mundane" and pretend["effects"] == [{"kind": "wait"}]
    claimed = clean_model_intent(
        {
            "schema_version": 2,
            "source": "supernatural",
            "player_request": "supernatural",
            "effects": [{"kind": "cosmetic"}],
        }
    )
    assert claimed["source"] == "supernatural" and claimed["effects"][0]["kind"] == "cosmetic"


def test_a_permanent_result_becomes_a_timed_one_and_the_cup_costs_three():
    from app.rules.universal.exploration import clean_model_intent

    raw = {
        "schema_version": 2,
        "source": "supernatural",
        "effects": [{"kind": "create_object", "lifetime": "permanent"}, {"kind": "cosmetic", "lifetime": "permanent"}],
    }
    cleaned = clean_model_intent(raw)
    assert [e["lifetime"] for e in cleaned["effects"][:1]] == ["timed"]
    cup = AbilityDefinitionV2(name="Кружка", source="supernatural", effects=[EffectIntentV2(kind="create_object")])
    assert exploration_cost(cup, 1) == 3  # one price unit for each six seconds of the eighteen
    with pytest.raises(ValidationError):
        EffectIntentV2(kind="create_object", lifetime="permanent")  # nothing the engine keeps is eternal


def test_a_term_named_by_the_player_is_priced_by_its_six_second_units():
    def spell(seconds):
        return AbilityDefinitionV2(
            name="Стена",
            source="supernatural",
            duration_seconds=seconds,
            effects=[EffectIntentV2(kind="create_object", template="structure", scale="medium")],
        )

    assert exploration_cost(spell(18), 1) == 12  # 4 per unit, three units
    assert exploration_cost(spell(60), 1) == 40  # ten units
    assert exploration_cost(spell(61), 1) == 44  # a started unit is paid for
    with pytest.raises(ValidationError):
        spell(604801)
