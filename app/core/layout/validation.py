"""Проверка blueprint до публикации (спецификация 2026-10-12, §3.2, §3.3, §4, §5).

Лимиты, совпадение концов прохода на плане, смысл краёв открытого участка, непрерывность дороги и ручья на стыке,
связность с входом и сюжетные обязательства; в конце — построение каждого участка (проходы не загорожены и
достижимы). Пустой список — blueprint можно фиксировать; иначе — что исправить.
"""

from __future__ import annotations

from collections import Counter, deque

from app.core import sketch
from app.core.layout.contracts import (
    EDGE_MEANINGS,
    ENVIRONMENTS,
    MATERIALS,
    MAX_AREAS,
    MAX_PASSAGES_PER_AREA,
    MAX_SIDE,
    OPPOSITE,
    PASSAGE_KINDS,
    PASSAGE_STATES,
    SHAPES,
    TERRAIN,
    VERTICAL,
    WIDE_KINDS,
    Area,
    Blueprint,
    Passage,
    boundary_cells,
    outward,
    side_len,
    terrain_cells,
)


def validate(bp: Blueprint) -> list[str]:
    errors: list[str] = []
    areas = {a.area_ref: a for a in bp.areas}
    if len(areas) != len(bp.areas):
        errors.append("area_ref повторяется")
    if not 1 <= len(bp.areas) <= MAX_AREAS:
        errors.append(f"участков {len(bp.areas)}: от 1 до {MAX_AREAS}, больше — следующий комплекс")
    if bp.entry not in areas:
        errors.append(f"вход {bp.entry}: нет такого участка")
    for a in bp.areas:
        errors += _area(a)
    errors += _overlaps(bp.areas)
    errors += [f"passage_ref {r} повторяется" for r, n in Counter(p.passage_ref for p in bp.passages).items() if n > 1]
    for p in bp.passages:
        errors += _passage(p, areas)
    errors += _crowding(bp)
    if errors:
        return errors  # дальше — проверки, которым нужны корректные участки и проходы
    errors += _edges(bp)
    errors += _joints(bp, areas)
    errors += _reachability(bp, areas)
    if errors:
        return errors
    from app.core.layout.geometry import GeometryError, build_area

    for a in bp.areas:
        try:
            build_area(bp, a)
        except GeometryError as e:
            errors += e.errors
    return errors


def _area(a: Area) -> list[str]:
    e: list[str] = []
    name = a.area_ref
    if a.shape not in SHAPES:
        e.append(f"{name}: форма {a.shape} не поддерживается")
    if a.environment not in ENVIRONMENTS:
        e.append(f"{name}: окружение {a.environment}")
    if a.material not in MATERIALS:
        e.append(f"{name}: материал {a.material}")
    if a.lighting not in {"normal", "dim", "dark"}:
        e.append(f"{name}: неизвестный режим освещения {a.lighting}")
    if not (1 <= a.cols <= MAX_SIDE and 1 <= a.rows <= MAX_SIDE):
        e.append(f"{name}: размер {a.cols}×{a.rows}, сторона от 1 до {MAX_SIDE}")
    if a.shape == "corridor" and min(a.cols, a.rows) > 2:
        e.append(f"{name}: коридор шире двух клеток")
    if a.shape == "open" and a.environment != "outdoor":
        e.append(f"{name}: открытая форма — только снаружи")
    if a.edges and a.environment != "outdoor":
        e.append(f"{name}: края со смыслом — только у открытого участка")

    def inside(r) -> bool:
        return len(r) == 4 and 0 <= r[0] <= r[2] < a.cols and 0 <= r[1] <= r[3] < a.rows

    for d in a.details:
        if d.kind not in sketch.FEATURE_KINDS:
            e.append(f"{name}: «{d.name}» — вид {d.kind}")
        if not d.cells or not all(inside(r) for r in d.cells):
            e.append(f"{name}: «{d.name}» за пределами участка")
    for t in a.terrain:
        if t.kind not in TERRAIN or not all(inside(r) for r in t.cells):
            e.append(f"{name}: рельеф {t.kind} за пределами участка или неизвестен")
    for g in a.edges:
        if g.side not in OPPOSITE or g.meaning not in EDGE_MEANINGS:
            e.append(f"{name}: край {g.side}/{g.meaning}")
        elif g.start < 0 or g.length < 1 or g.start + g.length > side_len(a, g.side):
            e.append(f"{name}: край {g.start}+{g.length} вне стороны {g.side}")
    return e


def _overlaps(areas: tuple[Area, ...]) -> list[str]:
    out = []
    for i, a in enumerate(areas):
        for b in areas[i + 1 :]:
            (ax, ay), (bx, by) = a.offset, b.offset
            if a.level == b.level and ax < bx + b.cols and bx < ax + a.cols and ay < by + b.rows and by < ay + a.rows:
                out.append(f"участки {a.area_ref} и {b.area_ref} пересекаются на плане уровня {a.level}")
    return out


def _passage(p: Passage, areas: dict[str, Area]) -> list[str]:
    e: list[str] = []
    name = f"проход {p.passage_ref}"
    if p.kind not in PASSAGE_KINDS:
        e.append(f"{name}: вид {p.kind}")
    if p.state not in PASSAGE_STATES:
        e.append(f"{name}: состояние {p.state}")
    if len(p.ends) != 2:
        return e + [f"{name}: нужно ровно два конца"]
    inner = [x for x in p.ends if not x.external]
    if not inner:
        return e + [f"{name}: оба конца вне комплекса"]
    for x in p.ends:
        if x.external:
            if not x.place_id:
                e.append(f"{name}: конец вне комплекса без place_id")
            continue
        a = areas.get(x.area_ref)
        if a is None:
            e.append(f"{name}: нет участка {x.area_ref}")
            continue
        if x.side not in OPPOSITE:
            e.append(f"{name}: сторона {x.side}")
            continue
        n = side_len(a, x.side)
        if x.width < 1 or x.start < 0 or x.start + x.width > n:
            e.append(f"{name}: интервал {x.start}+{x.width} вне стороны {x.side} участка {a.area_ref} длиной {n}")
        if x.width > 1 and p.kind not in WIDE_KINDS:
            e.append(f"{name}: шире одной клетки бывает только край, арка, ворота или пролом")
        if p.kind == "edge" and a.environment != "outdoor":
            e.append(f"{name}: свободный край — только у открытого участка")
    if e or len(inner) < 2:
        return e
    x, y = inner
    a, b = areas[x.area_ref], areas[y.area_ref]
    if a.area_ref == b.area_ref:
        return [f"{name}: проход ведёт в тот же участок"]
    if p.kind in VERTICAL:
        return [] if a.level != b.level else [f"{name}: лестница или люк соединяют разные уровни"]
    if a.level != b.level:
        return [f"{name}: участки на разных уровнях соединяет только лестница или люк"]
    if OPPOSITE[x.side] != y.side or x.width != y.width:
        return [f"{name}: концы не смотрят друг на друга"]
    dc, dr = outward(x.side)
    here = [(a.offset[0] + c + dc, a.offset[1] + r + dr) for c, r in boundary_cells(a, x.side, x.start, x.width)]
    there = [(b.offset[0] + c, b.offset[1] + r) for c, r in boundary_cells(b, y.side, y.start, y.width)]
    if here != there:
        return [f"{name}: концы не совпадают на плане ({a.area_ref} {x.side} ↔ {b.area_ref} {y.side})"]
    return []


def _crowding(bp: Blueprint) -> list[str]:
    e: list[str] = []
    count = Counter(x.area_ref for p in bp.passages for x in p.ends if not x.external)
    e += [f"у участка {r} {n} проходов, больше {MAX_PASSAGES_PER_AREA}" for r, n in count.items()
          if n > MAX_PASSAGES_PER_AREA]  # fmt: skip
    taken: dict[tuple[str, str], list[tuple[int, int, str]]] = {}
    for p in bp.passages:
        for x in p.ends:
            if x.external:
                continue
            for a0, a1, other in taken.get((x.area_ref, x.side), []):
                if x.start < a1 and a0 < x.start + x.width:
                    e.append(f"проходы {other} и {p.passage_ref} занимают одни клетки стороны {x.side} {x.area_ref}")
            taken.setdefault((x.area_ref, x.side), []).append((x.start, x.start + x.width, p.passage_ref))
    return e


def _edges(bp: Blueprint) -> list[str]:
    e: list[str] = []
    for a in bp.areas:
        if a.environment != "outdoor":
            continue
        ends = bp.ends_of(a.area_ref)
        for side in OPPOSITE:
            n = side_len(a, side)
            segs = [g for g in a.edges if g.side == side]
            cover = [0] * n
            for g in segs:
                for i in range(max(0, g.start), min(n, g.start + g.length)):
                    cover[i] += 1
            if any(v != 1 for v in cover):
                e.append(f"{a.area_ref}: край {side} должен быть разбит на отрезки без пропусков и наложений")
                continue
            for p, x in ends:
                if x.side != side:
                    continue
                seg = next((g for g in segs if g.start <= x.start and x.start + x.width <= g.start + g.length), None)
                if p.kind == "edge":
                    want = "boundary" if bp.other(p, x).external else "continuation"
                    ok = seg is not None and seg.meaning == want and (seg.start, seg.length) == (x.start, x.width)
                else:
                    want, ok = "obstacle", seg is not None and seg.meaning == "obstacle"
                if not ok:
                    e.append(
                        f"{a.area_ref}: проход {p.passage_ref} на стороне {side} — нужен край «{want}» точно по нему"
                    )
            for g in segs:
                if g.meaning != "obstacle" and not any(
                    p.kind == "edge" and x.side == side and (x.start, x.width) == (g.start, g.length) for p, x in ends
                ):
                    e.append(f"{a.area_ref}: край «{g.meaning}» на стороне {side} без прохода")
    return e


def _joints(bp: Blueprint, areas: dict[str, Area]) -> list[str]:
    """Дорога, тропа, ручей и мост на свободном крае продолжаются в соседнем участке теми же клетками плана."""
    e: list[str] = []
    for p in bp.passages:
        x, y = p.ends
        if p.kind != "edge" or x.external or y.external:
            continue
        a, b = areas[x.area_ref], areas[y.area_ref]
        ca, cb = boundary_cells(a, x.side, x.start, x.width), boundary_cells(b, y.side, y.start, y.width)
        for kind in sorted({t.kind for t in a.terrain} | {t.kind for t in b.terrain}):
            ta, tb = terrain_cells(a, kind), terrain_cells(b, kind)
            if [c in ta for c in ca] != [c in tb for c in cb]:
                e.append(f"стык {p.passage_ref}: «{kind}» обрывается между {a.area_ref} и {b.area_ref}")
    return e


def _reachability(bp: Blueprint, areas: dict[str, Area]) -> list[str]:
    def reach(public: bool) -> set[str]:
        seen = {bp.entry}
        q = deque([bp.entry])
        while q:
            for p, x in bp.ends_of(q.popleft()):
                if public and p.hidden:
                    continue
                o = bp.other(p, x)
                if o.area_ref and o.area_ref not in seen:
                    seen.add(o.area_ref)
                    q.append(o.area_ref)
        return seen

    every, public = reach(False), reach(True)
    e = [f"участок {r} не связан с входом" for r in areas if r not in every]
    for anchor, ref in sorted(bp.anchors.items()):
        if ref not in areas:
            e.append(f"привязка {anchor}: нет участка {ref}")
    for ref in sorted(set(bp.required) | set(bp.anchors.values())):
        if ref not in areas:
            e.append(f"обязательный участок {ref}: нет такого участка")
        elif ref not in public:
            e.append(f"обязательный участок {ref} доступен только через тайный проход")
    return e
