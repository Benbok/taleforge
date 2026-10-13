"""Пространственный замысел места из каркаса (спецификация 2026-10-12, §3.1) и мандат структуры (§3.2, §8).

``SpatialPlan`` пишет архитектор: окружение, масштаб, обязательные части и подходы — без клеток и предметов.
Первая часть — вход. ``Mandate`` — неизменная часть резерва ``location_layout``: замысел и сюжетные привязки места.
Из мандата структуру предлагает модель (app/agents/layout_model.py) или лестница детерминированных замыслов;
``obligations`` проверяет, что предложенный замысел каркас не нарушил.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.layout.contracts import MAX_AREAS
from app.core.layout.intent import REF, LayoutIntent

ROAD_KINDS = ("road", "path")
APPROACH_SIDES = ("w", "s", "e")
OUTDOOR_ROWS = {"small": 8, "medium": 10, "large": 12}  # как app/core/layout/provider.py SIZES["outdoor"]
MAX_HOLDERS = 8  # PartIntent.anchors: не больше восьми привязок на часть


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


class Holder(BaseModel):
    """То, что каркас обязал держать в одной части места: носитель зацепки или житель-NPC (``npc:<id>``)."""

    key: str = Field(pattern=r"^(npc:)?[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=80)


class Mandate(BaseModel):
    schema_version: Literal[1] = 1
    place: str = Field(min_length=1, max_length=128, description="публичное имя места")
    mood: str = Field("", max_length=300, description="настроение: необязательный контекст модели")
    spatial: SpatialPlan
    anchors: list[Holder] = Field(default_factory=list)
    residents: list[Holder] = Field(default_factory=list)

    @model_validator(mode="after")
    def _holders(self) -> Mandate:
        keys = [h.key for h in [*self.anchors, *self.residents]]
        if len(keys) > MAX_HOLDERS:
            raise ValueError(f"привязок места больше {MAX_HOLDERS}")
        if len(set(keys)) != len(keys):
            raise ValueError("привязка повторяется")
        return self

    def holders(self) -> list[Holder]:
        return [*self.anchors, *self.residents]


def intent_candidates(m: Mandate) -> list[LayoutIntent]:
    """Лестница замыслов: с дорогой у западного подхода → без полос → только первый подход. Первый — основной."""
    return [
        _intent(m, bands=True, approaches=3),
        _intent(m, bands=False, approaches=3),
        _intent(m, bands=False, approaches=1),
    ]


def _intent(m: Mandate, *, bands: bool, approaches: int) -> LayoutIntent:
    sp = m.spatial
    entry = sp.parts[0].ref
    aps = sp.approaches[:approaches]
    ap_sides = APPROACH_SIDES[: len(aps)]
    free = [s for s in ("n", "e", "s", "w") if s not in ap_sides]  # стороны входа для детей, не занятые подходами
    open_parts = [p for p in sp.parts if not p.secret]
    deep = next((p.ref for p in reversed(open_parts) if p.ref != entry and not p.below), None) or next(
        (p.ref for p in reversed(open_parts) if p.ref != entry), entry
    )
    out: list[dict] = []
    last: dict[int, str | None] = {0: None, -1: None}
    entry_kids = 0
    for i, p in enumerate(sp.parts):
        level = -1 if p.below else 0
        outdoor = p.outdoor and level == 0
        d = {
            "part_ref": p.ref,
            "role": "field" if outdoor else "room",
            "name": p.name,
            "public_name": p.name,
            "description": p.purpose,
            "environment": "outdoor" if outdoor else "indoor",
            "shape": "open" if outdoor else "rect",
            "size": "small" if p.secret else sp.scale,
            "level": level,
            "secret": p.secret,
            "required": p.required,
            "anchors": [],
        }
        if i > 0:
            parent = (last[0] if level == 0 else (last[-1] or last[0])) or entry
            same = next(x for x in out if x["part_ref"] == parent)["level"] == level
            if parent == entry and same:
                if entry_kids < len(free):
                    d["side"] = free[entry_kids]
                    entry_kids += 1
                else:  # стороны входа заняты подходами: часть встаёт за предыдущей открытой частью уровня
                    parent = next(
                        (
                            x["part_ref"]
                            for x in reversed(out)
                            if x["part_ref"] != entry and not x["secret"] and x["level"] == level
                        ),
                        entry,
                    )
            d["connects_to"] = parent
            d["passage_name"] = "Тайный ход" if p.secret else ("Лестница" if not same else "Проход")
            if not same:
                d["passage_kind"] = "stairs"
        if p.ref == deep:
            d["anchors"] += [h.key for h in m.anchors]
        if p.ref == entry:
            d["anchors"] += [h.key for h in m.residents]
        out.append(d)
        if not p.secret:
            last[level] = p.ref
    outdoor_entry = out[0]["environment"] == "outdoor"
    approaches_out, bands_out = [], []
    for side, ap in zip(ap_sides, aps, strict=True):
        a = {"part_ref": entry, "side": side, "kind": "edge" if outdoor_entry else "door", "public_name": ap.name}
        if bands and outdoor_entry and side == "w" and ap.kind in ROAD_KINDS:
            rows = OUTDOOR_ROWS[out[0]["size"]]
            bands_out.append({"band_ref": "road", "kind": ap.kind, "axis": "we", "at": rows // 2 - 1, "width": 2})
            a |= {"band": "road", "width": 2}
        approaches_out.append(a)
    return LayoutIntent.model_validate({"entry": entry, "parts": out, "approaches": approaches_out, "bands": bands_out})


def obligations(intent: LayoutIntent, m: Mandate) -> list[str]:
    """Что предложенный замысел нарушил в каркасе. Пусто — можно раскладывать."""
    errors: list[str] = []
    parts = {p.part_ref: p for p in intent.parts}
    entry = m.spatial.parts[0]
    if intent.entry != entry.ref:
        errors.append(f"вход — часть {entry.ref} «{entry.name}»")
    for sp in m.spatial.parts:
        p = parts.get(sp.ref)
        if p is None:
            errors.append(f"нет обязательной части {sp.ref} «{sp.name}»")
            continue
        if p.secret != sp.secret:
            errors.append(f"{sp.ref}: тайность части задана каркасом — {'тайная' if sp.secret else 'открытая'}")
        if sp.below and p.level >= 0:
            errors.append(f"{sp.ref}: часть уровнем ниже входа (level < 0)")
        if sp.required and not p.required:
            errors.append(f"{sp.ref}: сюжетная цель — required=true")
    held = Counter(a for p in intent.parts for a in p.anchors)
    for h in m.holders():
        if held[h.key] != 1:
            errors.append(f"«{h.name}» ({h.key}) — ровно в одной части, в её anchors")
    known = {h.key for h in m.holders()}
    errors += [f"неизвестная привязка {k}" for k in sorted(set(held) - known)]
    if len(intent.parts) > MAX_AREAS:
        errors.append(f"частей больше {MAX_AREAS}")
    if not intent.approaches:
        errors.append("нужен хотя бы один подход снаружи")
    errors += [
        f"подход «{a.public_name}»: снаружи — само место, outside_id не задаётся"
        for a in intent.approaches
        if a.outside_id is not None
    ]
    return errors
