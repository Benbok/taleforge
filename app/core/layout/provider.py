"""Детерминированный provider структуры (спецификация 2026-10-12, §3.2, §8): blueprint из замысла без модели.

Части укладываются по дереву ``connects_to``: ребёнок примыкает к родителю с заданной (или по seed выбранной)
стороны, по центру общей стены, без пересечений на своём уровне; часть другого уровня встаёт под родителем и
соединяется лестницей. Две открытые части соединяет свободный край во всю общую границу. ``fallback`` — упрощённая
цепочка на восток (тайные части — в конце): та же обязательная часть, те же привязки и путь к ним. Дорога, тропа и
ручей рисуются по полосам плана, поэтому на стыках совпадают сами; пересечение воды с дорогой — мост.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from app.core.layout.contracts import (
    OPPOSITE,
    VERTICAL,
    Area,
    Blueprint,
    Cell,
    Detail,
    Edge,
    End,
    LayoutError,
    ObjectSlot,
    Passage,
    Terrain,
    rect_cells,
    runs,
)
from app.core.layout.intent import ApproachIntent, BandIntent, LayoutIntent, PartIntent
from app.core.layout.validation import validate

SIZES = {
    "indoor": {"small": (5, 5), "medium": (7, 8), "large": (10, 12)},
    "outdoor": {"small": (9, 10), "medium": (14, 12), "large": (18, 14)},
}
CORRIDOR = (2, 8)
SIDE_ORDER = ("n", "e", "s", "w")
VERTICAL_SIDES = ("w", "n", "e", "s")
STACK_TRIES = 12


@dataclass(frozen=True)
class _Box:
    ox: int
    oy: int
    cols: int
    rows: int
    level: int

    def overlaps(self, o: _Box) -> bool:
        return (
            self.level == o.level
            and self.ox < o.ox + o.cols
            and o.ox < self.ox + self.cols
            and self.oy < o.oy + o.rows
            and o.oy < self.oy + self.rows
        )

    def length(self, side: str) -> int:
        return self.cols if side in ("n", "s") else self.rows

    def along(self, side: str) -> int:
        """Смещение стороны на плане по её оси."""
        return self.ox if side in ("n", "s") else self.oy


def _dims(part: PartIntent) -> tuple[int, int]:
    if part.cols and part.rows:
        return part.cols, part.rows
    if part.shape == "corridor":
        return CORRIDOR
    return SIZES[part.environment][part.size]


def _touching(p: _Box, side: str, cols: int, rows: int, level: int) -> _Box:
    if side == "n":
        return _Box(p.ox + (p.cols - cols) // 2, p.oy - rows, cols, rows, level)
    if side == "s":
        return _Box(p.ox + (p.cols - cols) // 2, p.oy + p.rows, cols, rows, level)
    if side == "w":
        return _Box(p.ox - cols, p.oy + (p.rows - rows) // 2, cols, rows, level)
    return _Box(p.ox + p.cols, p.oy + (p.rows - rows) // 2, cols, rows, level)


def _shared(p: _Box, c: _Box, side: str) -> tuple[int, int]:
    """Общий отрезок границы на плане: [lo, hi) по x для n/s, по y для e/w."""
    if side in ("n", "s"):
        return max(p.ox, c.ox), min(p.ox + p.cols, c.ox + c.cols)
    return max(p.oy, c.oy), min(p.oy + p.rows, c.oy + c.rows)


def _free(taken: list[tuple[int, int]], start: int, width: int) -> bool:
    return all(start + width <= a or b <= start for a, b in taken)


def _free_start(taken: list[tuple[int, int]], length: int, width: int) -> int | None:
    mid = (length - width) // 2
    for d in range(length):
        for s in (mid - d, mid + d):
            if 0 <= s <= length - width and _free(taken, s, width):
                return s
    return None


class DeterministicLayoutProvider:
    name = "deterministic"

    def propose(
        self, intent: LayoutIntent, *, seed: int, root_id: str, plot_id: str | None = None, fallback: bool = False
    ) -> Blueprint:
        by = {p.part_ref: p for p in intent.parts}
        parts = [by[intent.entry]] + [p for p in intent.parts if p.part_ref != intent.entry]
        if fallback:
            parts = parts[:1] + [p for p in parts[1:] if not p.secret] + [p for p in parts[1:] if p.secret]
        rng = random.Random(seed)
        boxes: dict[str, _Box] = {}
        taken: dict[tuple[str, str], list[tuple[int, int]]] = {}
        passages: list[Passage] = []
        errors: list[str] = []

        prev: PartIntent | None = None
        for part in parts:
            cols, rows = _dims(part)
            if prev is None:
                boxes[part.part_ref] = _Box(0, 0, cols, rows, part.level)
                prev = part
                continue
            parent = prev if fallback or part.connects_to is None else by[part.connects_to]
            pbox = boxes.get(parent.part_ref)
            if pbox is None:
                errors.append(f"«{part.name}»: родитель «{parent.name}» не уложен")
                continue
            if part.level != parent.level:
                passage = self._vertical(part, parent, pbox, cols, rows, boxes, taken)
                if passage is None:
                    errors.append(f"«{part.name}»: не уложить под «{parent.name}» или нет места для лестницы")
                    continue
                passages.append(passage)
                prev = part
                continue
            passage = self._beside(part, parent, pbox, cols, rows, boxes, taken, rng, fallback)
            if passage is None:
                errors.append(f"«{part.name}» не помещается рядом с «{parent.name}»")
                continue
            passages.append(passage)
            prev = part

        bands = {b.band_ref: b for b in intent.bands}
        for ap in intent.approaches:
            passage = self._approach(ap, by[ap.part_ref], boxes, taken, bands, root_id)
            if passage is None:
                errors.append(f"подход «{ap.public_name}»: нет места на стороне {ap.side}")
                continue
            passages.append(passage)

        terrain = _terrain(intent.bands, boxes, by)
        areas = []
        for part in parts:
            box = boxes.get(part.part_ref)
            if box is None:
                continue
            areas.append(_area(part, box, passages, terrain.get(part.part_ref, {})))
        anchors = {a: p.part_ref for p in parts for a in p.anchors}
        required = tuple(sorted({p.part_ref for p in parts if p.required or p.anchors}))
        bp = Blueprint(seed=seed, entry=intent.entry, areas=tuple(areas), passages=tuple(passages), anchors=anchors,
                       required=required, plot_id=plot_id)  # fmt: skip
        if not errors:
            bp = _place_details(bp)
            errors = validate(bp)
        if errors:
            raise LayoutError(errors)
        return bp

    def _vertical(self, part, parent, pbox, cols, rows, boxes, taken) -> Passage | None:
        box = None
        for k in range(STACK_TRIES):
            trial = _Box(pbox.ox + k * cols, pbox.oy, cols, rows, part.level)
            if not any(trial.overlaps(b) for b in boxes.values()):
                box = trial
                break
        if box is None:
            return None
        ends = []
        for ref, b in ((parent.part_ref, pbox), (part.part_ref, box)):
            for side in VERTICAL_SIDES:
                start = _free_start(taken.get((ref, side), []), b.length(side), 1)
                if start is not None:
                    taken.setdefault((ref, side), []).append((start, start + 1))
                    ends.append(End(ref, side, start, 1))
                    break
            else:
                return None
        boxes[part.part_ref] = box
        kind = part.passage_kind if part.passage_kind in VERTICAL else "stairs"
        return Passage(f"p_{part.part_ref}", kind, part.passage_name, part.passage_name, (ends[0], ends[1]),
                       part.passage_state, part.secret)  # fmt: skip

    def _beside(self, part, parent, pbox, cols, rows, boxes, taken, rng, fallback) -> Passage | None:
        if fallback:
            sides: list[str] = ["e"]
        else:
            order = list(SIDE_ORDER)
            rng.shuffle(order)
            sides = [part.side] + [s for s in order if s != part.side] if part.side else order
        both_out = part.environment == parent.environment == "outdoor"
        for side in sides:
            box = _touching(pbox, side, cols, rows, part.level)
            if any(box.overlaps(b) for b in boxes.values()):
                continue
            lo, hi = _shared(pbox, box, side)
            if hi <= lo:
                continue
            p_taken = taken.get((parent.part_ref, side), [])
            c_taken = taken.get((part.part_ref, OPPOSITE[side]), [])
            if both_out:
                spot, width = lo, hi - lo
                if not (
                    _free(p_taken, spot - pbox.along(side), width) and _free(c_taken, spot - box.along(side), width)
                ):
                    continue
            else:
                width = 1
                mid = lo + (hi - lo) // 2
                spot = next(
                    (
                        s
                        for d in range(hi - lo)
                        for s in (mid - d, mid + d)
                        if lo <= s < hi
                        and _free(p_taken, s - pbox.along(side), 1)
                        and _free(c_taken, s - box.along(side), 1)
                    ),
                    None,
                )
                if spot is None:
                    continue
            boxes[part.part_ref] = box
            pe = End(parent.part_ref, side, spot - pbox.along(side), width)
            ce = End(part.part_ref, OPPOSITE[side], spot - box.along(side), width)
            for e in (pe, ce):
                taken.setdefault((e.area_ref, e.side), []).append((e.start, e.start + e.width))
            kind = "edge" if both_out else part.passage_kind
            state = "open" if both_out else part.passage_state
            return Passage(f"p_{part.part_ref}", kind, part.passage_name, part.passage_name, (pe, ce), state,
                           part.secret)  # fmt: skip
        return None

    def _approach(self, ap: ApproachIntent, part, boxes, taken, bands, root_id) -> Passage | None:
        box = boxes.get(ap.part_ref)
        if box is None:
            return None
        length = box.length(ap.side)
        have = taken.get((ap.part_ref, ap.side), [])
        if ap.band is not None:
            band = bands[ap.band]
            if (band.axis == "we") != (ap.side in ("e", "w")):
                return None
            start, width = band.at - box.along(ap.side), band.width
            if not (0 <= start <= length - width and _free(have, start, width)):
                return None
        else:
            width = ap.width
            start = _free_start(have, length, width)
            if start is None:
                return None
        dc, dr = {"n": (0, -1), "s": (0, 1), "w": (-1, 0), "e": (1, 0)}[ap.side]
        for i in range(width):
            c, r = {"n": (start + i, 0), "s": (start + i, box.rows - 1), "w": (0, start + i),
                    "e": (box.cols - 1, start + i)}[ap.side]  # fmt: skip
            outside = _Box(box.ox + c + dc, box.oy + r + dr, 1, 1, box.level)
            if any(outside.overlaps(b) for b in boxes.values()):
                return None  # подход упирается в соседний участок
        taken.setdefault((ap.part_ref, ap.side), []).append((start, start + width))
        kind = ap.kind if part.environment == "outdoor" or ap.kind != "edge" else "door"
        return Passage(f"in_{ap.part_ref}_{ap.side}", kind, ap.public_name, ap.public_name,
                       (End(ap.part_ref, ap.side, start, width), End(place_id=ap.outside_id or root_id)))  # fmt: skip


def _edges(ref: str, box: _Box, passages: list[Passage]) -> tuple[Edge, ...]:
    out: list[Edge] = []
    for side in ("n", "e", "s", "w"):
        marks = sorted(
            (x.start, x.width, "boundary" if p.ends[1 - i].external else "continuation")
            for p in passages
            if p.kind == "edge"
            for i, x in enumerate(p.ends)
            if x.area_ref == ref and x.side == side
        )
        pos = 0
        for start, width, meaning in marks:
            if start > pos:
                out.append(Edge(side, pos, start - pos, "obstacle"))
            out.append(Edge(side, start, width, meaning))
            pos = start + width
        if pos < box.length(side):
            out.append(Edge(side, pos, box.length(side) - pos, "obstacle"))
    return tuple(out)


def _terrain(bands: list[BandIntent], boxes: dict[str, _Box], by: dict[str, PartIntent]) -> dict[str, dict]:
    out: dict[str, dict[str, set[Cell]]] = {}
    for ref, box in boxes.items():
        if by[ref].environment != "outdoor":
            continue
        kinds: dict[str, set[Cell]] = {}
        for b in bands:
            lo = -(10**6) if b.start is None else b.start
            hi = 10**6 if b.end is None else b.end
            for c in range(box.cols):
                for r in range(box.rows):
                    x, y = box.ox + c, box.oy + r
                    across, along = (y, x) if b.axis == "we" else (x, y)
                    if b.at <= across < b.at + b.width and lo <= along < hi:
                        kinds.setdefault(b.kind, set()).add((c, r))
        bridge = kinds.get("stream", set()) & (kinds.get("road", set()) | kinds.get("path", set()))
        if bridge:
            for k in ("stream", "road", "path"):
                if k in kinds:
                    kinds[k] -= bridge
            kinds["bridge"] = bridge
        out[ref] = kinds
    return out


def _area(part: PartIntent, box: _Box, passages: list[Passage], terrain: dict[str, set[Cell]]) -> Area:
    details = tuple(
        Detail(d.detail_ref, d.name, d.kind, tuple(tuple(r) for r in d.cells), d.solid, d.hidden, d.visual_key)  # type: ignore[misc]
        for d in part.details
    )
    outdoor = part.environment == "outdoor"
    return Area(
        area_ref=part.part_ref,
        role=part.role,
        name=part.name,
        public_name=part.public_name,
        environment=part.environment,
        shape=part.shape,
        cols=box.cols,
        rows=box.rows,
        offset=(box.ox, box.oy),
        level=part.level,
        material=part.material or ("grass" if outdoor else "stone"),
        description=part.description,
        secret=part.secret,
        scene_profile=part.scene_profile,
        lighting=part.lighting,
        object_slots=tuple(
            ObjectSlot(
                s.slot_ref, s.role, tuple(tuple(r) for r in s.cells), s.detail_ref, s.hidden, s.max_cols, s.max_rows
            )
            for s in part.object_slots
        ),
        details=details,
        terrain=tuple(Terrain(k, tuple(runs(cells))) for k, cells in sorted(terrain.items()) if cells),
        edges=_edges(part.part_ref, box, passages) if outdoor else (),
    )


def _place_details(bp: Blueprint) -> Blueprint:
    """Keep landmarks on the actual floor, relocating conflicts instead of dropping them.

    All map features occupy cells, including non-solid scenery. Placement checks
    actual reachability, including full-width outdoor edges, before accepting them.
    If a supplied detail cannot fit, reject the proposal so the caller can retry.
    """
    from app.core.layout import geometry

    areas = []
    for area in bp.areas:
        floor = geometry.area_floor(bp, area)
        entrances = {
            c for _, end in bp.ends_of(area.area_ref) for c in geometry.end_cells(floor, area, end) if c is not None
        }
        occupied: set[Cell] = set()
        details = list(area.details)
        placed = []

        def fits(
            detail: Detail, *, floor=floor, entrances=entrances, occupied=occupied, area=area, placed=placed
        ) -> bool:
            cells = rect_cells(detail.cells)
            if not cells <= floor:
                return False
            if cells & (entrances | occupied):
                return False
            try:
                interim = {d.detail_ref: d for d in [*placed, detail]}
                slots = tuple(
                    replace(s, cells=interim[s.detail_ref].cells) if s.detail_ref else s
                    for s in area.object_slots
                    if not s.detail_ref or s.detail_ref in interim
                )
                geometry.build_area(bp, replace(area, details=tuple([*placed, detail]), object_slots=slots))
            except geometry.GeometryError:
                return False
            return True

        # Fixed solid geometry takes precedence over cosmetic marks.
        for d in sorted(details, key=lambda d: not d.solid):
            cells = rect_cells(d.cells)
            if fits(d):
                placed.append(d)
                occupied |= cells
                continue
            candidates = sorted(
                ((dc, dr) for dc in range(-area.cols + 1, area.cols) for dr in range(-area.rows + 1, area.rows)),
                key=lambda shift: (abs(shift[0]) + abs(shift[1]), shift[1], shift[0]),
            )
            for dc, dr in candidates:
                shifted = {(c + dc, r + dr) for c, r in cells}
                moved = replace(d, cells=tuple((c0 + dc, r0 + dr, c1 + dc, r1 + dr) for c0, r0, c1, r1 in d.cells))
                if fits(moved):
                    placed.append(moved)
                    occupied |= shifted
                    break
            else:
                raise LayoutError([f"{area.area_ref}: деталь «{d.name}» не помещается без перекрытия проходов"])
        by_ref = {d.detail_ref: d for d in placed}
        slots = tuple(
            replace(s, cells=by_ref[s.detail_ref].cells) if s.detail_ref in by_ref else s for s in area.object_slots
        )
        if not slots and area.role in {"market", "cache", "pier"}:
            from app.core.layout import furnish

            base = geometry.build_area(bp, replace(area, details=tuple(by_ref.values()), object_slots=()))
            proposed, unplaced = furnish.place(
                base, [("slot_candidate", "Container")], bp.seed, roles={"slot_candidate": "container"}
            )
            if not unplaced:
                feature = next(f for f in proposed["features"] if f.get("entity_id") == "slot_candidate")
                slots = (ObjectSlot(f"{area.role}_container", "container", tuple(tuple(r) for r in feature["cells"])),)
        from app.core.layout import scenery

        areas.append(
            scenery.populate(
                bp,
                replace(
                    area,
                    details=tuple(by_ref[d.detail_ref] for d in details if d.detail_ref in by_ref),
                    object_slots=slots,
                ),
            )
        )
    from app.core.layout.lighting import arrange

    result = replace(bp, areas=tuple(arrange(bp, area) for area in areas))
    for area in result.areas:
        geometry.build_area(result, area)
    return result
