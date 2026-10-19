"""Optional map dressing from stable area semantics, without spawning world objects or loot."""

from __future__ import annotations

import random
from dataclasses import replace

from app.core import reach
from app.core.layout import geometry
from app.core.layout.contracts import Area, Blueprint, Cell, Detail, rect_cells
from app.core.layout.intent import LayoutIntent
from app.core.layout.spatial import Mandate
from app.core.layout.template_roles import infer_role

# A motif is placed atomically: a seating group keeps its authored relative spacing.
_SEATING = (
    ("table", "Стол", "furniture", (0, 1, 1, 1)),
    ("bench", "Скамья", "furniture", (0, 0, 1, 0)),
    ("bench", "Скамья", "furniture", (0, 2, 1, 2)),
)
_PROPS = {
    "hearth": ("Очаг", "furniture", (0, 0, 1, 0)),
    "bed": ("Кровать", "furniture", (0, 0, 1, 0)),
    "chest": ("Ларь", "furniture", (0, 0, 0, 0)),
    "shelf": ("Стеллаж", "furniture", (0, 0, 0, 2)),
    "crate": ("Сложенные ящики", "furniture", (0, 0, 1, 0)),
    "barrel": ("Бочка", "furniture", (0, 0, 0, 0)),
    "bench": ("Скамья", "furniture", (0, 0, 1, 0)),
    "table": ("Рабочий стол", "furniture", (0, 0, 1, 0)),
    "counter": ("Прилавок", "furniture", (0, 0, 2, 0)),
    "torch": ("Светильник", "light", (0, 0, 0, 0)),
    "altar": ("Алтарь", "furniture", (0, 0, 1, 0)),
    "pillar": ("Колонна", "cover", (0, 0, 0, 0)),
    "net": ("Сложенная сеть", "furniture", (0, 0, 1, 0)),
    "mooring": ("Швартовная тумба", "furniture", (0, 0, 0, 0)),
    "rock": ("Каменные выступы", "nature", (0, 0, 1, 0)),
    "rubble": ("Осыпь", "nature", (0, 0, 0, 0)),
    "lichen": ("Лишайник", "nature", (0, 0, 1, 0)),
    "crystal": ("Кристаллы", "nature", (0, 0, 0, 0)),
    "tree": ("Дерево", "nature", (0, 0, 0, 0)),
    "shrub": ("Кустарник", "nature", (0, 0, 1, 0)),
    "reeds": ("Камыши", "nature", (0, 0, 1, 0)),
    "chair": ("Кресло", "furniture", (0, 0, 0, 0)),
    "desk": ("Письменный стол", "furniture", (0, 0, 1, 0)),
    "wardrobe": ("Шкаф", "furniture", (0, 0, 1, 0)),
    "weapon_rack": ("Оружейная стойка", "furniture", (0, 0, 1, 0)),
    "workbench": ("Верстак", "furniture", (0, 0, 1, 0)),
    "anvil": ("Наковальня", "object", (0, 0, 0, 0)),
    "forge": ("Кузнечный горн", "light", (0, 0, 1, 0)),
    "cauldron": ("Котёл", "object", (0, 0, 0, 0)),
    "chandelier": ("Люстра", "light", (0, 0, 0, 0)),
    "brazier": ("Жаровня", "light", (0, 0, 0, 0)),
    "statue": ("Статуя", "cover", (0, 0, 0, 0)),
    "fountain": ("Фонтан", "object", (0, 0, 1, 1)),
    "well": ("Колодец", "object", (0, 0, 1, 1)),
    "sarcophagus": ("Саркофаг", "cover", (0, 0, 1, 0)),
    "tombstone": ("Надгробие", "cover", (0, 0, 0, 0)),
    "cart": ("Телега", "cover", (0, 0, 1, 1)),
    "cage": ("Клетка", "object", (0, 0, 0, 0)),
    "carpet": ("Ковёр", "furniture", (0, 0, 1, 1)),
    "stump": ("Пень", "nature", (0, 0, 0, 0)),
    "log": ("Поваленное бревно", "nature", (0, 0, 1, 0)),
    "mushrooms": ("Грибы", "nature", (0, 0, 0, 0)),
    "sack": ("Мешки", "object", (0, 0, 0, 0)),
}


def _motifs(area: Area) -> list[tuple]:
    role = area.role
    if role in {"prison_cell", "prison", "jail", "cell", "cells", "holding_cell"}:
        return [
            (("bench", "Грубые нары", "furniture", (0, 0, 1, 0)),),
            (("rubble", *_PROPS["rubble"]),),
        ]
    if area.shape == "cave" or role in {"cave", "grotto", "cavern", "cliff", "cliffs", "rocky_slope"}:
        keys = (
            ("rock", "rubble", "lichen", "crystal")
            if area.shape == "cave"
            else ("rock", "rubble", "lichen", "mushrooms")
        )
    elif role in {"pier", "quay", "dock", "cargo_pier"}:
        keys = ("mooring", "net", "barrel", "crate", "sack", "cart")
    elif role in {"warehouse", "storage", "store", "cellar", "pantry", "cache"}:
        keys = ("shelf", "crate", "barrel", "chest", "sack", "wardrobe")
    elif role in {"crypt", "tomb"}:
        keys = ("sarcophagus", "tombstone", "brazier", "pillar", "statue")
    elif role in {"chapel", "temple", "shrine", "sanctuary"}:
        keys = ("altar", "bench", "torch", "pillar", "statue", "brazier", "carpet")
    elif role in {"bedroom", "guest_room", "guest_rooms", "sleeping", "barracks", "dormitory"}:
        keys = ("bed", "chest", "torch", "bench", "wardrobe", "chair", "carpet")
    elif role in {"workshop", "smithy"}:
        keys = ("workbench", "anvil", "forge", "weapon_rack", "table", "barrel")
    elif role in {"kitchen"}:
        keys = ("table", "hearth", "cauldron", "shelf", "barrel", "sack")
    elif role in {"laboratory", "study", "library", "office"}:
        keys = ("desk", "chair", "shelf", "carpet", "table", "torch")
    elif role in {"market", "shop", "stall"}:
        keys = ("counter", "crate", "barrel", "shelf", "sack")
    elif area.environment == "outdoor":
        keys = (
            ("reeds", "shrub", "rock", "log")
            if role in {"bank", "riverbank", "marsh"}
            else ("tree", "shrub", "rock", "stump", "log", "mushrooms")
        )
    elif role in {"common_room"}:
        keys = ("hearth", "torch", "barrel")
        return [_SEATING, *[((key, *_PROPS[key]),) for key in keys]]
    elif role in {"tavern", "dining", "dining_room", "hall", "great_hall"}:
        keys = ("hearth", "torch", "barrel", "chair", "chandelier", "carpet")
        return [_SEATING, *[((key, *_PROPS[key]),) for key in keys]]
    else:
        return []
    return [((key, *_PROPS[key]),) for key in keys]


def populate(bp: Blueprint, area: Area) -> Area:
    """Supplement sparse areas, preserving every supplied detail and its artwork."""
    if area.role in {"room", "start", "entry", "area", "generic"}:
        role = infer_role(area.area_ref, area.name, area.description)
        if role is not None:
            area = replace(area, role=role)
    if area.role in {"prison", "jail", "cell", "cells", "holding_cell"}:
        area = replace(area, role="prison_cell")
    unfurnished = ("без мебели", "без предметов", "полностью пуст", "no furniture", "unfurnished", "empty room")
    if area.role == "corridor" or any(word in area.description.casefold() for word in unfurnished):
        return area
    if len(area.details) >= 3 or area.material == "water" or area.shape == "corridor" or min(area.cols, area.rows) < 4:
        return area
    base = geometry.build_area(bp, area)
    floor = geometry.area_floor(bp, area)
    keep = {tuple(base["party"])}
    for exit_ in base["exits"]:
        for c, r in exit_["cells"]:
            keep |= {(c + dc, r + dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1)}
    # A clear cross gives larger rooms readable working aisles before reachability checks.
    if min(area.cols, area.rows) >= 8:
        keep |= {
            (c, r)
            for c, r in floor
            if c in (area.cols // 2 - 1, area.cols // 2) or r in (area.rows // 2 - 1, area.rows // 2)
        }
    for terrain in area.terrain:
        keep |= rect_cells(terrain.cells)
    for slot in area.object_slots:
        keep |= rect_cells(slot.cells)
    budget = min(8, len(area.details) + 3 + len(floor) // 32)
    if area.role == "prison_cell":
        budget = min(budget, 2)
    motifs = _motifs(area)
    if area.lighting != "normal":
        motifs = [motif for motif in motifs if not any(p[2] == "light" or p[0] == "hearth" for p in motif)]
    if not motifs:
        return area
    anchors = sorted(floor - keep)
    random.Random(geometry.area_seed(bp.seed, area.area_ref)).shuffle(anchors)
    boundary = {
        cell
        for cell in floor
        if any((cell[0] + dc, cell[1] + dr) not in floor for dc, dr in ((0, 1), (0, -1), (1, 0), (-1, 0)))
    }
    placed: list[Detail] = list(area.details)
    occupied: set[Cell] = set().union(*(rect_cells(d.cells) for d in placed))
    used_refs = {d.detail_ref for d in placed}
    for index in range(budget):
        motif = motifs[index % len(motifs)]
        if len(placed) + len(motif) > budget:
            continue
        refs = []
        for i in range(len(motif)):
            ref = f"decor_{index}_{i}"
            while ref in used_refs:
                ref += "_"
            refs.append(ref)
        # Prefer perimeter anchors and spread separate groups around the room.
        candidates = sorted(
            anchors,
            key=lambda cell: (
                min(abs(cell[0] - c) + abs(cell[1] - r) for c, r in boundary),
                -min((abs(cell[0] - c) + abs(cell[1] - r) for c, r in occupied), default=0),
            ),
        )
        for c, r in candidates[:96]:
            group = tuple(
                Detail(
                    refs[i],
                    name,
                    kind,
                    ((c + x0, r + y0, c + x1, r + y1),),
                    visual_key=f"feature:{key}",
                )
                for i, (key, name, kind, (x0, y0, x1, y1)) in enumerate(motif)
            )
            cells = set().union(*(rect_cells(d.cells) for d in group))
            margin = {(x + dc, y + dr) for x, y in occupied for dc in (-1, 0, 1) for dr in (-1, 0, 1)}
            if not cells <= floor or cells & (keep | margin):
                continue
            trial = replace(area, details=tuple([*placed, *group]))
            try:
                sk = geometry.build_area(bp, trial)
            except geometry.GeometryError:
                continue
            # Keep every decorative group approachable as well as all exits connected.
            region = reach.walk_region(sk, tuple(sk["party"]))
            if any(not reach.approach_cells(sk, f) & region for f in sk["features"]):
                continue
            placed.extend(group)
            used_refs.update(refs)
            occupied |= cells
            break
    return replace(area, details=tuple(placed))


_DETAILS = {
    "market": ("market_stalls", "Рыночные прилавки", "furniture", False),
    "warehouse": ("warehouse_crates", "Штабели ящиков", "cover", True),
    "cache": ("cache_marker", "Спрятанный тайник", "object", True),
    "alley": ("alley_lantern", "Портовый фонарь", "light", False),
}


def enrich_intent(intent: LayoutIntent, mandate: Mandate) -> LayoutIntent:
    parts = intent.model_dump(mode="json")
    for part in parts["parts"]:
        requested = next((p for p in mandate.spatial.parts if p.ref == part["part_ref"]), None)
        if requested is None:
            continue
        role = infer_role(requested.ref, requested.name, requested.purpose)
        detail = _DETAILS.get(role)
        if detail is not None:
            detail_ref, name, kind, hidden = detail
            if any(d["detail_ref"] == detail_ref for d in part["details"]):
                continue
            part["details"].append(
                {
                    "detail_ref": detail_ref,
                    "name": name,
                    "kind": kind,
                    "cells": [[1, 1, 2, 1]],
                    "solid": False,
                    "hidden": hidden,
                }
            )
        elif role == "harbor" and requested.material is None:
            part["material"] = "water"
    return LayoutIntent.model_validate(parts)
