from app.core.world import _universal_actor
from app.db.models import Character
from app.rules.universal.contracts import AbilityScores, HeroDescription, StartingEquipment, UniversalSheet

SCORES = dict(str=8, dex=12, con=14, int=13, wis=15, cha=10)


def hero(initialized):
    item = dict(name="Thing", description="A plain thing", reason="Fits the hero")
    sheet = UniversalSheet(
        abilities=AbilityScores(**SCORES),
        description=HeroDescription(identity="Traveler"),
        starting_equipment=StartingEquipment(
            weapon=dict(kind="weapon", attack_ability="str", **item), armor=dict(kind="armor", **item)
        ),
    )
    resources = {"inventory_initialized": True} if initialized else {}
    return Character(id="ch_1", name="Hero", sheet=sheet.model_dump(mode="json"), resources=resources)


def test_uninitialised_inventory_keeps_starting_armor():
    assert _universal_actor(hero(False), []).ac == 14


def test_initialised_inventory_without_items_has_no_starting_armor():
    # everything was dropped or given away: resolution must agree with the card, which shows no armor
    assert _universal_actor(hero(True), []).ac == 13
