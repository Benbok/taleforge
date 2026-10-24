from types import SimpleNamespace

from app.core.characters import full_view
from app.core.universal.state import game_card_of
from app.gateway.protocol import CharacterSheet, SnapshotCampaign
from app.rules.universal.contracts import UniversalSheet


def hero():
    sheet = UniversalSheet(
        abilities=dict(str=8, dex=10, con=12, int=13, wis=14, cha=15), description=dict(identity="Путник")
    )
    return SimpleNamespace(
        id="h",
        name="Путник",
        portrait_id=None,
        seat_id="seat",
        status="active",
        sheet=sheet.model_dump(mode="json"),
        resources={
            "hp": "19",
            "learned_abilities": [
                {"id": "ability", "name": "Зелёный свет", "profile_ref": "green", "profile_revision": "1"}
            ],
        },
    )


def test_saved_game_card_exposes_successfully_learned_abilities():
    card = game_card_of(hero())
    assert card["learned_abilities"][0]["profile_ref"] == "green"
    assert card["hp"] == "19"
    assert card["editable"] is False


def test_websocket_sheet_accepts_universal_card_and_full_view_skips_legacy_catalog():
    card = full_view(hero(), None, [], [])
    wire = CharacterSheet(character=card).model_dump(mode="json")
    assert wire["character"]["sheet"]["rules_version"] == "universal.v1"
    assert wire["character"]["energies"]["wis"] == "24"


def test_snapshot_identifies_the_rules_used_by_the_game():
    wire = SnapshotCampaign(id="c", name="Мир", status="active", public_intro="В путь", ruleset_id="universal")
    assert wire.ruleset_id == "universal"


def test_ability_card_projects_actual_level_cost_and_saved_limits():
    h = hero()
    h.resources["learned_abilities"][0]["profile"] = dict(id="green", attribute="wis", kind="check", resource_key="wis")
    ability = game_card_of(h)["learned_abilities"][0]
    assert ability["cost"] == "3"
    assert ability["resource_key"] == "wis"
    assert ability["limits"]["targets"] == "1"
    assert ability["description"] == "Зелёный свет"
