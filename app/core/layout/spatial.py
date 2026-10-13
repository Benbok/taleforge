"""Пространственный замысел места из каркаса (спецификация 2026-10-12, §3.1) и мандат структуры (§3.2, §8).

``SpatialPlan`` пишет архитектор: окружение, масштаб, обязательные части и подходы — без клеток и предметов.
Первая часть — вход. ``Mandate`` — неизменная часть резерва ``location_layout``: замысел и сюжетные привязки места.
Из мандата структуру предлагает модель (app/agents/layout_model.py) или лестница детерминированных замыслов;
``obligations`` проверяет, что предложенный замысел каркас не нарушил.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.layout.intent import REF


class SpatialPart(BaseModel):
    ref: str = Field(pattern=REF, description="id части внутри места: nave, crypt")
    name: str = Field(min_length=1, max_length=80, description="название для героев, без тайн")
    purpose: str = Field("", max_length=300, description="что здесь, одной фразой")
    outdoor: bool = Field(False, description="открытая местность: поле, двор, берег")
    below: bool = Field(False, description="уровнем ниже входа: подвал, крипта")
    secret: bool = Field(False, description="за тайным проходом")
    required: bool = Field(False, description="сюжетная цель: к ней обязан вести открытый путь")

    @model_validator(mode="after")
    def _shape(self) -> SpatialPart:
        if self.secret and self.required:
            raise ValueError(f"{self.ref}: тайная часть не может быть обязательной целью")
        if self.below and self.outdoor:
            raise ValueError(f"{self.ref}: часть уровнем ниже — помещение, а не открытая местность")
        return self


class SpatialApproach(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="как герои подходят: «Дорога из деревни»")
    kind: Literal["road", "path", "door", "gate", "gap"] = "path"


class SpatialPlan(BaseModel):
    schema_version: Literal[1] = 1
    environment: Literal["indoor", "outdoor", "mixed"]
    scale: Literal["small", "medium", "large"] = "medium"
    parts: list[SpatialPart] = Field(min_length=1, max_length=6)
    approaches: list[SpatialApproach] = Field(min_length=1, max_length=3)
    links: list[str] = Field(default_factory=list, max_length=4, description="id других мест каркаса рядом")

    @model_validator(mode="after")
    def _parts(self) -> SpatialPlan:
        refs = [p.ref for p in self.parts]
        if len(set(refs)) != len(refs):
            raise ValueError("ref части повторяется")
        entry = self.parts[0]
        if entry.secret or entry.below:
            raise ValueError("первая часть — вход: не тайная и не уровнем ниже")
        outdoor = {p.outdoor for p in self.parts}
        if self.environment == "indoor" and True in outdoor:
            raise ValueError("indoor: открытых частей нет")
        if self.environment == "outdoor" and not entry.outdoor:
            raise ValueError("outdoor: вход — открытая местность")
        if self.environment == "mixed" and outdoor != {True, False}:
            raise ValueError("mixed: нужны и открытые части, и помещения")
        return self
