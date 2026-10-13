from app.core.scene_presentation import scene_presentation
from app.db.models import Entity


def location(name: str, state: dict | None = None) -> Entity:
    return Entity(id="loc_test", campaign_id="camp_test", kind="location", name=name, state=state or {})


def test_absent_location_has_no_presentation():
    assert scene_presentation(None) is None


def test_public_name_matching_does_not_invent_weather_or_period():
    out = scene_presentation(location("Старая таверна"))
    assert out is not None
    assert out.preset == "tavern"
    assert out.period is None
    assert out.weather is None


def test_matching_uses_words_and_priority():
    assert scene_presentation(location("Невинное место")).preset == "neutral"
    assert scene_presentation(location("Крипта у храма")).preset == "crypt"


def test_explicit_presentation_is_public_and_keeps_only_allowed_fields():
    out = scene_presentation(
        location(
            "Бухта",
            {
                "secret": "не показывать",
                "presentation": {
                    "preset": "coast",
                    "period": "dusk",
                    "weather": "fog",
                    "illustration_key": "salt_bay",
                },
            },
        )
    )
    assert out.model_dump() == {
        "preset": "coast",
        "period": "dusk",
        "weather": "fog",
        "illustration_key": "salt_bay",
    }


def test_invalid_legacy_presentation_falls_back_without_leaking_state():
    out = scene_presentation(location("Нейтральное место", {"presentation": {"weather": "storm"}, "secret": "x"}))
    assert out.model_dump() == {"preset": "neutral", "period": None, "weather": None, "illustration_key": None}
