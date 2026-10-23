import pytest
from pydantic import ValidationError

from app.rules.universal.contracts import AbilityScores, HeroDescription, UniversalSheet
from app.rules.universal.mechanics import derive, validate_starting_scores

SCORES = dict(str=8, dex=12, con=14, int=13, wis=15, cha=10)


@pytest.mark.parametrize("bad", [dict.fromkeys(SCORES, 15), {**SCORES, "str": 9, "cha": 9}])
def test_start_array_is_exact(bad):
    with pytest.raises(ValueError):
        validate_starting_scores(AbilityScores(**bad))


@pytest.mark.parametrize("level,hp", [(1, 24), (5, 48), (10, 78), (100, 618)])
def test_hp_tracks_level_and_constitution(level, hp):
    sheet = UniversalSheet(
        level=level, abilities=AbilityScores(**SCORES), description=HeroDescription(identity="Botanist")
    )
    assert derive(sheet, []).hp_max == hp


def test_five_reserves_and_defense():
    scores = AbilityScores(**dict.fromkeys(SCORES, 14))
    sheet = UniversalSheet(abilities=scores, description=HeroDescription(identity="Traveler"))
    result = derive(sheet, [])
    assert result.energy_max == dict(str=24, dex=24, int=24, wis=24, cha=24)
    assert result.ac == 14
    assert result.modifiers["con"] == 2


def test_counts_roundtrip_above_javascript_precision():
    sheet = UniversalSheet(
        level="9007199254740993", abilities=AbilityScores(**SCORES), description=HeroDescription(identity="Traveler")
    )
    assert sheet.model_dump(mode="json")["level"] == "9007199254740993"
    assert UniversalSheet.model_validate_json(sheet.model_dump_json()).level == 9007199254740993
    assert derive(sheet, []).hp_max == 54043195528445976


@pytest.mark.parametrize("value", [True, 1.5, "1e10", "-1", "01"])
def test_counts_reject_ambiguous_or_inexact_values(value):
    with pytest.raises(ValidationError):
        UniversalSheet(level=value, abilities=AbilityScores(**SCORES), description=HeroDescription(identity="Traveler"))
