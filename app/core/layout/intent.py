"""Пространственный замысел комплекса (спецификация 2026-10-12, §3.1, §3.2): что предлагает ведущий или модель.

Без клеток стен и списка каждого предмета: части с ролью, размером и формой, к какой части примыкает каждая и с
какой стороны, подходы снаружи и сквозные полосы рельефа (дорога, тропа, ручей) в координатах плана, где начало —
северо-западный угол входной части. Обязательные привязки каркаса — ``anchors`` и ``required``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

REF = r"^[a-z][a-z0-9_]{0,31}$"
Side = Literal["n", "e", "s", "w"]


class DetailIntent(BaseModel):
    detail_ref: str = Field(pattern=REF)
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["furniture", "cover", "hazard", "light", "object", "nature"] = "object"
    cells: list[list[int]] = Field(min_length=1, max_length=4, description="[c0, r0, c1, r1] в клетках части")
    solid: bool = Field(False, description="колонна, валун: непроходимая геометрия, не предмет")
    hidden: bool = False


class PartIntent(BaseModel):
    part_ref: str = Field(pattern=REF)
    role: str = Field("room", max_length=32)
    name: str = Field(min_length=1, max_length=128, description="для мастера")
    public_name: str = Field(min_length=1, max_length=128, description="что видят герои")
    description: str = Field("", max_length=1000)
    environment: Literal["indoor", "outdoor"] = "indoor"
    shape: Literal["rect", "circle", "l_shape", "corridor", "open", "cave"] = "rect"
    size: Literal["small", "medium", "large"] = "medium"
    cols: int | None = Field(None, ge=1, le=30)
    rows: int | None = Field(None, ge=1, le=30)
    level: int = Field(0, ge=-3, le=3)
    material: Literal["stone", "earth", "grass", "water", "wood"] | None = None
    connects_to: str | None = Field(None, description="часть выше по списку; пусто — предыдущая")
    side: Side | None = Field(None, description="с какой стороны родителя примыкает")
    passage_kind: Literal["door", "gate", "arch", "passage", "stairs", "hatch", "gap"] = "door"
    passage_name: str = Field("Проход", min_length=1, max_length=60)
    passage_state: Literal["open", "closed", "locked"] = "open"
    secret: bool = Field(False, description="часть за тайным проходом")
    required: bool = Field(False, description="к части обязан вести не тайный путь")
    anchors: list[str] = Field(default_factory=list, max_length=8, description="зацепки каркаса в этой части")
    details: list[DetailIntent] = Field(default_factory=list, max_length=16)


class ApproachIntent(BaseModel):
    part_ref: str
    side: Side
    kind: Literal["edge", "door", "gate", "arch", "passage", "gap"] = "edge"
    public_name: str = Field(min_length=1, max_length=60)
    outside_id: str | None = Field(None, description="место снаружи; пусто — само корневое место")
    band: str | None = Field(None, description="полоса рельефа, по которой идёт подход")
    width: int = Field(1, ge=1, le=30)


class BandIntent(BaseModel):
    band_ref: str = Field(pattern=REF)
    kind: Literal["road", "path", "stream"]
    axis: Literal["we", "ns"] = Field(description="we — с запада на восток (ряды), ns — с севера на юг (столбцы)")
    at: int = Field(description="первый ряд (we) или столбец (ns) полосы на плане")
    width: int = Field(1, ge=1, le=4)
    start: int | None = Field(None, description="протяжённость по другой оси, полуинтервал [start, end)")
    end: int | None = None


class LayoutIntent(BaseModel):
    schema_version: Literal[1] = 1
    entry: str
    parts: list[PartIntent] = Field(min_length=1, max_length=12)
    approaches: list[ApproachIntent] = Field(default_factory=list, max_length=8)
    bands: list[BandIntent] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _refs(self) -> LayoutIntent:
        refs = [p.part_ref for p in self.parts]
        if len(set(refs)) != len(refs):
            raise ValueError("part_ref повторяется")
        if self.entry not in refs:
            raise ValueError(f"entry {self.entry}: нет такой части")
        seen = {self.entry}
        for p in self.parts:
            if p.part_ref == self.entry:
                continue
            if p.connects_to is not None and p.connects_to not in seen:
                raise ValueError(f"{p.part_ref}: connects_to должен ссылаться на часть выше по списку")
            seen.add(p.part_ref)
        bands = {b.band_ref for b in self.bands}
        for a in self.approaches:
            if a.part_ref not in seen:
                raise ValueError(f"подход «{a.public_name}»: нет части {a.part_ref}")
            if a.band is not None and a.band not in bands:
                raise ValueError(f"подход «{a.public_name}»: нет полосы {a.band}")
        return self
