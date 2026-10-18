"""Пространственный замысел комплекса (спецификация 2026-10-12, §3.1, §3.2): что предлагает ведущий или модель.

Без клеток стен и списка каждого предмета: части с ролью, размером и формой, к какой части примыкает каждая и с
какой стороны, подходы снаружи и сквозные полосы рельефа (дорога, тропа, ручей) в координатах плана, где начало —
северо-западный угол входной части. Обязательные привязки каркаса — ``anchors`` и ``required``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.layout.contracts import MAX_SIDE

REF = r"^[a-z][a-z0-9_]{0,31}$"
Side = Literal["n", "e", "s", "w"]

# Optional presentation metadata shared with the map artwork catalogue.
# Unknown saved keys remain valid and use the client's category fallback.
DETAIL_VISUAL_KEYS = (
    "feature:table",
    "feature:bench",
    "feature:bed",
    "feature:counter",
    "feature:shelf",
    "feature:barrel",
    "feature:crate",
    "feature:chest",
    "feature:hearth",
    "feature:torch",
    "feature:altar",
    "feature:pillar",
    "feature:rock",
    "feature:rubble",
    "feature:tree",
    "feature:shrub",
    "feature:reeds",
    "feature:crystal",
    "feature:bones",
    "feature:net",
    "feature:crane",
    "feature:mooring",
    "feature:glow",
    "feature:lichen",
    "feature:nest",
    "feature:chair",
    "feature:desk",
    "feature:wardrobe",
    "feature:weapon_rack",
    "feature:workbench",
    "feature:anvil",
    "feature:forge",
    "feature:cauldron",
    "feature:chandelier",
    "feature:brazier",
    "feature:statue",
    "feature:fountain",
    "feature:well",
    "feature:sarcophagus",
    "feature:tombstone",
    "feature:cart",
    "feature:cage",
    "feature:carpet",
    "feature:stump",
    "feature:log",
    "feature:mushrooms",
    "feature:sack",
)


class DetailIntent(BaseModel):
    detail_ref: str = Field(pattern=REF)
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["furniture", "cover", "hazard", "light", "object", "nature"] = "object"
    cells: list[list[int]] = Field(min_length=1, max_length=4, description="[c0, r0, c1, r1] в клетках части")
    solid: bool = Field(False, description="колонна, валун: непроходимая геометрия, не предмет")
    hidden: bool = False
    visual_key: str | None = Field(None, max_length=64)

    @field_validator("cells")
    @classmethod
    def _cells(cls, rects: list[list[int]]) -> list[list[int]]:
        for r in rects:
            if len(r) != 4:
                raise ValueError("прямоугольник детали: ровно четыре числа [c0, r0, c1, r1]")
            c0, r0, c1, r1 = r
            if not (0 <= c0 <= c1 < MAX_SIDE and 0 <= r0 <= r1 < MAX_SIDE):
                raise ValueError(f"прямоугольник детали вне части: 0 <= c0 <= c1 < {MAX_SIDE}, то же для рядов")
        return rects


class ObjectSlotIntent(BaseModel):
    slot_ref: str = Field(pattern=REF)
    role: Literal["prop", "container", "item"]
    cells: list[list[int]] = Field(min_length=1, max_length=4)
    detail_ref: str | None = Field(None, pattern=REF)
    hidden: bool = False
    max_cols: int = Field(1, ge=1, le=30)
    max_rows: int = Field(1, ge=1, le=30)

    @field_validator("cells")
    @classmethod
    def _cells(cls, rects: list[list[int]]) -> list[list[int]]:
        return DetailIntent._cells(rects)


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
    lighting: Literal["normal", "dim", "dark"] = "normal"
    connects_to: str | None = Field(None, description="часть выше по списку; пусто — предыдущая")
    side: Side | None = Field(None, description="с какой стороны родителя примыкает")
    passage_kind: Literal["door", "gate", "arch", "passage", "stairs", "hatch", "gap"] = "door"
    passage_name: str = Field("Проход", min_length=1, max_length=60)
    passage_state: Literal["open", "closed", "locked"] = "open"
    secret: bool = Field(False, description="часть за тайным проходом")
    required: bool = Field(False, description="к части обязан вести не тайный путь")
    anchors: list[str] = Field(default_factory=list, max_length=8, description="зацепки каркаса в этой части")
    details: list[DetailIntent] = Field(default_factory=list, max_length=16)
    scene_profile: str | None = Field(None, max_length=128)
    object_slots: list[ObjectSlotIntent] = Field(default_factory=list, max_length=32)


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
            slots = [s.slot_ref for s in p.object_slots]
            if len(set(slots)) != len(slots):
                raise ValueError(f"{p.part_ref}: slot_ref повторяется")
            if p.part_ref == self.entry:
                continue
            if p.connects_to is not None and p.connects_to not in seen:
                raise ValueError(f"{p.part_ref}: connects_to должен ссылаться на часть выше по списку")
            seen.add(p.part_ref)
        anchor_owner: dict[str, str] = {}
        for p in self.parts:
            for a in p.anchors:
                if anchor_owner.setdefault(a, p.part_ref) != p.part_ref:
                    raise ValueError(f"зацепка {a} указана в двух частях")
            drefs = [d.detail_ref for d in p.details]
            if len(set(drefs)) != len(drefs):
                raise ValueError(f"{p.part_ref}: detail_ref повторяется")
        bands = {b.band_ref for b in self.bands}
        for a in self.approaches:
            if a.part_ref not in seen:
                raise ValueError(f"подход «{a.public_name}»: нет части {a.part_ref}")
            if a.band is not None and a.band not in bands:
                raise ValueError(f"подход «{a.public_name}»: нет полосы {a.band}")
        return self
