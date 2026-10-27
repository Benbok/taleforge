from types import SimpleNamespace

from app.core.universal.places import START_LOCATION_NAME, public_location_name


def place(state, name="Кампания"):
    campaign = SimpleNamespace(ruleset_id="universal", name="Кампания")
    return campaign, SimpleNamespace(kind="location", name=name, state=state)


def test_entry_placeholder_gives_way_to_the_prepared_scene_title():
    campaign, entry = place({"studio_entry": True})
    assert public_location_name(campaign, entry) == START_LOCATION_NAME
    campaign, entry = place({"studio_entry": True, "universal_scene": {"ready": True, "title": "Провал Серой Глотки"}})
    assert public_location_name(campaign, entry) == "Провал Серой Глотки"


def test_authored_names_are_never_replaced_by_a_scene_title():
    campaign, entry = place({"universal_scene": {"title": "Другое"}}, name="Таверна")
    assert public_location_name(campaign, entry) == "Таверна"
