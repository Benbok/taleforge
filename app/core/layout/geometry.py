"""Геометрия участка из blueprint (спецификация 2026-10-12, §3.3): маска пола, твёрдые детали, проходы и их клетки.

Без модели и сети: тот же blueprint и seed всегда дают тот же эскиз. Результат — эскиз в формате
app/core/sketch.py, его читают и сервер движения, и карта. Сервер проверяет, что проходы не загорожены и до каждого
можно дойти от точки входа участка (``party``).
"""

from __future__ import annotations

import zlib

from app.core import reach, sketch
from app.core.layout import shapes
from app.core.layout.contracts import Area, Blueprint, Cell, End, LayoutError, rect_cells

SKETCH_SHAPE = {"rect": "room", "circle": "room", "l_shape": "room", "corridor": "corridor", "open": "open",
                "cave": "cave"}  # fmt: skip


class GeometryError(LayoutError):
    """Участок нельзя построить по blueprint: проход без пола, загорожен или отрезан."""


def area_seed(seed: int, area_ref: str) -> int:
    return zlib.crc32(f"{seed}:{area_ref}".encode()) & 0x7FFFFFFF


def end_cells(floor: set[Cell], area: Area, end: End) -> list[Cell | None]:
    return [shapes.inner_cell(floor, area.cols, area.rows, end.side, end.start + i) for i in range(end.width)]


def area_floor(bp: Blueprint, area: Area) -> set[Cell]:
    seed = area_seed(bp.seed, area.area_ref)
    if area.shape != "cave":
        return shapes.floor(area.shape, area.cols, area.rows, seed)
    base = shapes.floor("circle", area.cols, area.rows, seed)
    keep = frozenset(c for _, x in bp.ends_of(area.area_ref) for c in end_cells(base, area, x) if c is not None)
    return shapes.floor("cave", area.cols, area.rows, seed, keep)


def _center(cells: set[Cell], area: Area) -> Cell:
    if not cells:
        raise GeometryError([f"{area.area_ref}: у участка нет свободного пола"])
    return min(cells, key=lambda c: (abs(c[0] - area.cols // 2) + abs(c[1] - area.rows // 2), c[1], c[0]))


def build_area(bp: Blueprint, area: Area, *, root_id: str | None = None, ids: dict[str, str] | None = None) -> dict:
    ids = ids or {}
    floor = area_floor(bp, area)
    errors: list[str] = []
    solid: set[Cell] = set()
    features: list[dict] = []
    for d in area.details:
        cells = rect_cells(d.cells)
        if not cells <= floor:
            errors.append(f"{area.area_ref}: «{d.name}» вне пола")
        if d.solid:
            solid |= cells
        else:
            features.append({
                "id": f"sf_{area.area_ref}_{d.detail_ref}"[:32], "name": d.name, "kind": d.kind,
                "cells": [list(r) for r in d.cells], "cover": "none", "hidden": d.hidden,
            })  # fmt: skip
    exits: list[dict] = []
    for p, x in sorted(bp.ends_of(area.area_ref), key=lambda t: (t[0].hidden, t[0].passage_ref)):
        cells = end_cells(floor, area, x)
        if any(c is None for c in cells):
            errors.append(f"{area.area_ref}: у прохода {p.passage_ref} нет пола внутри")
            continue
        o = bp.other(p, x)
        exits.append({
            "name": p.public_name, "side": x.side, "at": x.start, "width": x.width, "kind": p.kind,
            "state": p.state, "hidden": p.hidden, "to": ids.get(o.area_ref) if o.area_ref else o.place_id,
            "beyond": None, "passage_ref": p.passage_ref, "cells": [list(c) for c in cells],
        })  # fmt: skip
    if errors:
        raise GeometryError(errors)
    party = tuple(exits[0]["cells"][0]) if exits else _center(floor - solid, area)
    sk: dict = {
        "shape": SKETCH_SHAPE[area.shape],
        "cols": area.cols,
        "rows": area.rows,
        "party": list(party),
        "walls": [list(c) for c in sorted(solid)],
        "exits": exits,
        "features": features,
        "environment": area.environment,
        "material": area.material,
        "terrain": [{"kind": t.kind, "cells": [list(r) for r in t.cells]} for t in area.terrain],
        "edges": [{"side": g.side, "start": g.start, "length": g.length, "meaning": g.meaning} for g in area.edges],
        "blueprint": {"root_id": root_id, "area_ref": area.area_ref, "rev": bp.revision},
    }
    if len(floor) != area.cols * area.rows:
        sk["mask"] = sketch.encode_mask(floor, area.cols, area.rows)
    errors = sketch.check(sk, {x["to"] for x in exits if x["to"]})
    blocked = reach.blocked_cells(sk)
    errors += [
        f"{area.area_ref}: проход {x['passage_ref']} загорожен"
        for x in exits
        if any(tuple(c) in blocked for c in x["cells"])
    ]
    if not errors:
        region = reach.walk_region(sk, party)
        errors += [
            f"{area.area_ref}: к проходу {x['passage_ref']} не пройти от входа участка"
            for x in exits
            if not any(tuple(c) in region for c in x["cells"])
        ]
    if errors:
        raise GeometryError(errors)
    return sk
