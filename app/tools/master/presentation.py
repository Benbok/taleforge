"""Инструмент мастера для публичного декоративного оформления места."""

from __future__ import annotations

import copy
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.scene_presentation import LocationPresentation
from app.tools.registry import ToolContext, ToolError, tool


class SetLocationPresentationArgs(BaseModel):
    location_id: str
    preset: Literal["neutral", "tavern", "coast", "forest", "ruins", "crypt", "sanctuary"] = "neutral"
    period: Literal["dawn", "day", "dusk", "night"] | None = None
    weather: Literal["clear", "cloudy", "rain", "fog", "snow"] | None = None
    illustration_key: str | None = Field(None, max_length=64)

    @field_validator("illustration_key")
    @classmethod
    def valid_illustration_key(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[a-z0-9_-]{1,64}", value):
            raise ValueError("ключ иллюстрации должен содержать только a-z, 0-9, _ или -")
        return value


@tool(
    "set_location_presentation",
    "Меняет только публичное декоративное оформление зарегистрированной локации: мотив, время суток, погоду и иллюстрацию.",
    SetLocationPresentationArgs,
    closes=False,
)
async def set_location_presentation(ctx: ToolContext, a: SetLocationPresentationArgs) -> dict:
    location = ctx.world.entities.get(a.location_id)
    if location is None or location.kind != "location":
        raise ToolError(f"нет локации {a.location_id}")
    before = copy.deepcopy(location.state or {})
    presentation = LocationPresentation(
        preset=a.preset,
        period=a.period,
        weather=a.weather,
        illustration_key=a.illustration_key,
    ).model_dump()
    location.state = {**before, "presentation": presentation}
    await ctx.record(
        "set_location_presentation",
        target_id=location.id,
        payload={"location_id": location.id, "presentation": presentation},
        inverse=[{"table": "entities", "id": location.id, "field": "state", "before": before}],
    )
    return {"location_id": location.id, "presentation": presentation}
