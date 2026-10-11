"""Footprint, клетки взаимодействия и достижимость объектов эскиза (спецификация генерации сцен, §5;
docs/world-objects-delivery1.md).

Привязанный к детали эскиза объект занимает все её клетки: дистанция до него — до ближайшей клетки footprint,
а не до северо-западного якоря рисования. ``access_sides`` детали — стороны (n/e/s/w), с которых к ней подходят;
без него — с любой стороны, по диагонали тоже (как ходят по сетке). Клетки взаимодействия вычисляются каждый раз
из footprint и сторон, вторым набором координат не хранятся. Координаты эскиза — от северо-западного угла;
клетки героев — от строя отряда (``positions.to_rel``/``to_master``).
"""

from __future__ import annotations

from collections import deque

SIDE_DELTA = {"n": (0, -1), "e": (1, 0), "s": (0, 1), "w": (-1, 0)}
DIRS = [(dc, dr) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if dc or dr]

Cell = tuple[int, int]


def footprint(feature: dict) -> set[Cell]:
    return {
        (c, r) for c0, r0, c1, r1 in feature.get("cells") or [] for c in range(c0, c1 + 1) for r in range(r0, r1 + 1)
    }


def feature_of(sk: dict | None, entity_id: str) -> dict | None:
    return next((f for f in (sk or {}).get("features") or [] if f.get("entity_id") == entity_id), None)


def _inside(sk: dict, c: Cell) -> bool:
    return 0 <= c[0] < sk["cols"] and 0 <= c[1] < sk["rows"]


def _walls(sk: dict) -> set[Cell]:
    return {(int(x[0]), int(x[1])) for x in sk.get("walls") or []}


def blocked_cells(sk: dict) -> set[Cell]:
    out = _walls(sk)
    for f in sk.get("features") or []:
        out |= footprint(f)
    return out


def _corner(at: Cell, dc: int, dr: int, walls: set[Cell]) -> bool:
    return bool(dc and dr) and (at[0] + dc, at[1]) in walls and (at[0], at[1] + dr) in walls


def approach_cells(sk: dict, feature: dict) -> set[Cell]:
    """Свободные клетки, откуда можно взаимодействовать с деталью: примыкают к footprint с разрешённой стороны."""
    fp = footprint(feature)
    blocked = blocked_cells(sk)
    walls = _walls(sk)
    sides = feature.get("access_sides") or None
    deltas = [SIDE_DELTA[s] for s in sides if s in SIDE_DELTA] if sides else DIRS
    out: set[Cell] = set()
    for c, r in fp:
        for dc, dr in deltas:
            n = (c + dc, r + dr)
            if n in fp or n in blocked or not _inside(sk, n):
                continue
            if _corner((c, r), dc, dr, walls):
                continue
            out.add(n)
    return out


def walk_region(sk: dict, start: Cell) -> set[Cell]:
    """Клетки, куда можно дойти от ``start`` (8 направлений, без прохода сквозь стык двух стен)."""
    blocked = blocked_cells(sk)
    walls = _walls(sk)
    if not _inside(sk, start):
        return set()
    seen = {start}
    q = deque([start])
    while q:
        cur = q.popleft()
        for dc, dr in DIRS:
            n = (cur[0] + dc, cur[1] + dr)
            if n in seen or n in blocked or not _inside(sk, n) or _corner(cur, dc, dr, walls):
                continue
            seen.add(n)
            q.append(n)
    return seen


def exit_cell(sk: dict, x: dict) -> Cell:
    """Клетка места у выхода: с неё в него входят."""
    at, side = int(x["at"]), x["side"]
    if side == "n":
        return at, 0
    if side == "s":
        return at, sk["rows"] - 1
    if side == "w":
        return 0, at
    return sk["cols"] - 1, at


def reach_errors(sk: dict) -> list[str]:
    """Привязанные объекты не отрезают выходы, к каждому из них есть достижимая клетка взаимодействия.

    Мерой служит тот же эскиз без привязанных объектов: выход, закрытый стеной или декоративной деталью (лаз под
    нарами), — замысел рисунка, а не ошибка размещения объекта. Временные позиции героев и существ препятствием не
    считаются; недоступная декоративная деталь без объекта допустима."""
    errors: list[str] = []
    features = sk.get("features") or []
    linked = [f for f in features if f.get("entity_id")]
    if not linked:
        return errors
    party = (int(sk["party"][0]), int(sk["party"][1]))
    region = walk_region(sk, party)
    baseline = walk_region({**sk, "features": [f for f in features if not f.get("entity_id")]}, party)
    taken: dict[Cell, str] = {}
    for f in linked:
        for cell in footprint(f):
            taken.setdefault(cell, f["name"])
    for x in sk.get("exits") or []:
        cell = exit_cell(sk, x)
        if not _inside(sk, cell) or cell not in baseline or cell in region:
            continue
        if cell in taken:
            errors.append(f"«{taken[cell]}» загораживает выход «{x['name']}»")
        else:
            errors.append(f"«{', '.join(f['name'] for f in linked)}» отрезает выход «{x['name']}» от отряда")
    for f in linked:
        cells = approach_cells(sk, f)
        if not cells:
            errors.append(f"к «{f['name']}» не подойти: нет свободной клетки с доступной стороны")
        elif not cells & region:
            errors.append(f"к «{f['name']}» не подойти от отряда")
    return errors


# --- позиции в мире: клетки героев от строя отряда ---


def object_feature(world, entity) -> tuple[dict, dict] | None:
    """(физический эскиз, деталь) привязанного объекта в его комнате или None."""
    from app.core import positions as grid

    if entity is None or entity.location_id is None:
        return None
    sk = grid._sketch(world, entity.location_id)
    f = feature_of(sk, entity.id)
    return (sk, f) if sk and f else None


def object_cells(world, entity) -> set[Cell] | None:
    """Footprint объекта в клетках от строя отряда; None — объект не привязан к эскизу."""
    found = object_feature(world, entity)
    if found is None:
        return None
    sk, f = found
    ax, ay = int(sk["party"][0]), int(sk["party"][1])
    return {(c - ax, r - ay) for c, r in footprint(f)}


def nearest_rel(cells: set[Cell], to: Cell = (0, 0)) -> Cell:
    return min(cells, key=lambda c: (max(abs(c[0] - to[0]), abs(c[1] - to[1])), c[1], c[0]))


def object_distance(world, actor_id: str, entity) -> int:
    """Футы от участника до объекта: до ближайшей клетки footprint, иначе до точки объекта."""
    from app.core import positions as grid
    from app.core import steps

    cells = object_cells(world, entity)
    if cells:
        me = steps.cell_of(world, actor_id)
        d = min(max(abs(c[0] - me[0]), abs(c[1] - me[1])) for c in cells)
        return max(5, d * 5)
    return grid.distance(grid.pos_of(world, actor_id), grid.pos_of(world, entity.id))


def approach_rel(world, entity) -> set[Cell] | None:
    """Клетки подхода к привязанному объекту от строя отряда; None — объект не привязан."""
    found = object_feature(world, entity)
    if found is None:
        return None
    sk, f = found
    ax, ay = int(sk["party"][0]), int(sk["party"][1])
    return {(c - ax, r - ay) for c, r in approach_cells(sk, f)}


def approach_for_near(world, place: str | None, near: list[Cell]) -> set[Cell] | None:
    """Игрок выбрал на схеме деталь со сторонами подхода: идти к её клеткам подхода, а не к любой соседней."""
    from app.core import positions as grid

    sk = grid._sketch(world, place)
    if not sk:
        return None
    ax, ay = int(sk["party"][0]), int(sk["party"][1])
    want = {(c + ax, r + ay) for c, r in near}
    for f in sk.get("features") or []:
        if f.get("access_sides") and footprint(f) == want:
            return {(c - ax, r - ay) for c, r in approach_cells(sk, f)}
    return None


def approach_route(world, actor_id: str, entity, *, fighting: bool) -> tuple[str | None, list[Cell] | None]:
    """Может ли участник дотянуться до объекта: (причина отказа, путь к клетке подхода).

    Путь пустой — уже стоит у объекта. В бою подходят своим ходом, поэтому путь не строится."""
    from app.core import steps

    cells = approach_rel(world, entity)
    if cells is None:
        return None, []
    me = steps.cell_of(world, actor_id)
    if me in cells:
        return None, []
    sides = (object_feature(world, entity) or ({}, {}))[1].get("access_sides")
    side_note = " с доступной стороны" if sides else ""
    if fighting:
        return f"до «{entity.name}» не дотянуться: подойдите вплотную{side_note}", None
    route = steps.search(world, entity.location_id, me, lambda c: c in cells, actor_id)
    if route is None:
        return f"к «{entity.name}» не подойти{side_note}: путь закрыт", None
    return None, route
