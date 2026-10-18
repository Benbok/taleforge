"""Mount authored sconces and distribute optional light without erasing scene darkness."""

from __future__ import annotations

import math
from dataclasses import replace

from app.core import reach, sketch
from app.core.layout import geometry
from app.core.layout.contracts import Area, Blueprint, Detail, rect_cells

_NEIGHBORS = ((0, -1), (1, 0), (0, 1), (-1, 0))


def target_count(floor_cells: int) -> int:
    return 1 if floor_cells <= 25 else min(8, max(2, math.ceil(floor_cells / 40)))


def _details(area: Area, details: list[Detail]) -> Area:
    by_ref = {d.detail_ref: d for d in details}
    slots = tuple(
        replace(s, cells=by_ref[s.detail_ref].cells) if s.detail_ref in by_ref else s for s in area.object_slots
    )
    return replace(area, details=tuple(details), object_slots=slots)


def arrange(bp: Blueprint, area: Area) -> Area:
    """Only an existing visible torch/hearth calls for normal room-light supplementation.

    A natural glow, a hidden fixture or an outdoor fire never invents wall torches.
    Torches are fixtures; hearths and other authored objects retain their footprint.
    All new placements still pass the ordinary geometry/reachability checks.
    """
    if area.environment != "indoor" or area.shape in {"open", "corridor"} or area.material == "water":
        return area
    fixtures = [d.detail_ref for d in area.details if d.visual_key == "feature:torch" and not d.hidden and not d.solid]
    fires = [d for d in area.details if d.visual_key in {"feature:torch", "feature:hearth"} and not d.hidden]
    if not fires:
        return area
    floor = geometry.area_floor(bp, area)
    boundary = sorted((c, r) for c, r in floor if any((c + dc, r + dr) not in floor for dc, dr in _NEIGHBORS))
    base = geometry.build_area(bp, area)

    def inaccessible(sk: dict, candidate: Area) -> set[tuple[str, str]]:
        region = reach.walk_region(sk, tuple(sk["party"]))
        blocked = {("detail", str(i)) for i, f in enumerate(sk["features"]) if not reach.approach_cells(sk, f) & region}
        blocked |= {
            ("slot", slot.slot_ref)
            for slot in candidate.object_slots
            if not reach.approach_cells(sk, {"cells": slot.cells}) & region
        }
        return blocked

    baseline_inaccessible = inaccessible(base, area)
    keep = {tuple(base["party"])}
    for exit_ in base["exits"]:
        for c, r in exit_["cells"]:
            keep |= {(c + dc, r + dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1)}
    for terrain in area.terrain:
        keep |= rect_cells(terrain.cells)
    current = area

    def place(detail: Detail, candidates: list[tuple[int, int]]) -> bool:
        nonlocal current
        others = [d for d in current.details if d.detail_ref != detail.detail_ref]
        occupied = set().union(*(rect_cells(d.cells) for d in others))
        reserved = set().union(
            *(rect_cells(s.cells) for s in current.object_slots if s.detail_ref != detail.detail_ref)
        )
        free = [cell for cell in candidates if cell not in keep | occupied | reserved]
        for c, r in free[:48]:
            mounted = replace(detail, cells=((c, r, c, r),))
            # Preserve order and stable references of existing fixtures and attached slots.
            trial_details = [mounted if d.detail_ref == detail.detail_ref else d for d in current.details]
            if not any(d.detail_ref == detail.detail_ref for d in current.details):
                trial_details.append(mounted)
            trial = _details(current, trial_details)
            try:
                sk = geometry.build_area(bp, trial)
            except geometry.GeometryError:
                continue
            if reach.reach_errors(sk) or not inaccessible(sk, trial) <= baseline_inaccessible:
                continue
            current = trial
            return True
        return False

    def distributed(lit: set[tuple[int, int]]) -> list[tuple[int, int]]:
        uncovered = {cell for cell in floor if all((cell[0] - x) ** 2 + (cell[1] - y) ** 2 > 25 for x, y in lit)}
        return sorted(
            boundary,
            key=lambda c: (
                -sum((c[0] - x) ** 2 + (c[1] - y) ** 2 <= 25 for x, y in uncovered),
                -min(((c[0] - x) ** 2 + (c[1] - y) ** 2 for x, y in lit), default=0),
                c,
            ),
        )

    settled = set().union(
        *(rect_cells(d.cells) for d in current.details if d.visual_key == "feature:hearth" and not d.hidden)
    )
    boundary_set = set(boundary)
    for ref in fixtures:
        detail = next(d for d in current.details if d.detail_ref == ref)
        original = rect_cells(detail.cells)
        spread = original <= boundary_set and all(
            (c - x) ** 2 + (r - y) ** 2 >= 16 for c, r in original for x, y in settled
        )
        candidates = (
            distributed(settled)
            if area.lighting == "normal" and settled and not spread
            else sorted(boundary, key=lambda c: (min((c[0] - x) ** 2 + (c[1] - y) ** 2 for x, y in original), c))
        )
        place(detail, candidates)
        settled |= rect_cells(next(d for d in current.details if d.detail_ref == ref).cells)
    if area.lighting != "normal":
        return current
    target = target_count(len(floor))
    existing = [d for d in current.details if not d.hidden and d.visual_key in {"feature:torch", "feature:hearth"}]
    for index in range(max(0, target - len(existing))):
        if len(current.details) >= sketch.MAX_FEATURES:
            break
        lit = set().union(
            *(
                rect_cells(d.cells)
                for d in current.details
                if not d.hidden and d.visual_key in {"feature:torch", "feature:hearth"}
            )
        )
        candidates = distributed(lit)
        ref = f"wall_torch_{index}"
        while any(d.detail_ref == ref for d in current.details):
            ref += "_"
        if not place(Detail(ref, "Настенный факел", "light", ((0, 0, 0, 0),), visual_key="feature:torch"), candidates):
            break
    return current
