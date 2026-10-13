"""Публичное декоративное оформление текущей локации.

Оформление не является частью механики мира: оно берётся только из явного
публичного state.presentation или из безопасного мотива имени места.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.db.models import Entity

Preset = Literal["neutral", "tavern", "coast", "forest", "ruins", "crypt", "sanctuary"]
Period = Literal["dawn", "day", "dusk", "night"]
Weather = Literal["clear", "cloudy", "rain", "fog", "snow"]

_IMAGE_KEY = re.compile(r"^[a-z0-9_-]{1,64}$")
_PRESET_WORDS: tuple[tuple[Preset, frozenset[str]], ...] = (
    ("crypt", frozenset({"склеп", "крипта", "катакомбы", "crypt", "catacombs"})),
    ("sanctuary", frozenset({"храм", "святилище", "temple", "sanctuary"})),
    ("tavern", frozenset({"таверна", "трактир", "tavern", "inn"})),
    ("coast", frozenset({"бухта", "берег", "порт", "coast", "harbor"})),
    ("forest", frozenset({"лес", "forest"})),
    ("ruins", frozenset({"руины", "ruins"})),
)


class LocationPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: Preset = "neutral"
    period: Period | None = None
    weather: Weather | None = None
    illustration_key: str | None = Field(None, max_length=64)

    @field_validator("illustration_key")
    @classmethod
    def _image_key(cls, value: str | None) -> str | None:
        if value is not None and not _IMAGE_KEY.fullmatch(value):
            raise ValueError("ключ иллюстрации должен содержать только a-z, 0-9, _ или -")
        return value


def _words(name: str) -> set[str]:
    return set(re.findall(r"[\w’'-]+", name.casefold(), flags=re.UNICODE))


def _fallback(name: str) -> LocationPresentation:
    words = _words(name)
    for preset, candidates in _PRESET_WORDS:
        if words & candidates:
            return LocationPresentation(preset=preset)
    return LocationPresentation()


def scene_presentation(location: Entity | None) -> LocationPresentation | None:
    """Возвращает только безопасный публичный снимок оформления места."""
    if location is None:
        return None
    raw = (location.state or {}).get("presentation")
    if raw is None:
        return _fallback(location.name)
    if not isinstance(raw, dict):
        return _fallback(location.name)
    try:
        return LocationPresentation.model_validate(raw)
    except ValidationError:
        return _fallback(location.name)
