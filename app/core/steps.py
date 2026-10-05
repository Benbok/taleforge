"""Ход по клеткам (design/interactive-map.md, шаги 2 и 3; решение Arty 2026-10-05: значок двигается сразу).

Игрок нажимает клетку на схеме — герой идёт туда кратчайшим путём в обход стен, предметов эскиза и занятых клеток
(по сетке SRD: восемь направлений, каждая клетка 5 футов). Вне боя путь ограничен только местом. В бою — ходом героя:
до скорости свободно, дальше, до двух скоростей, — рывок (тратит действие). Уход из досягаемости враждебного
существа провоцирует атаку по возможности: клиент сперва предупреждает, а на подтверждение сервер её разыгрывает.

Без эскиза схема клиента — квадрат ``LIMIT`` клеток во все стороны от строя: дальше идти некуда.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Any

from app.core import positions as grid

LIMIT = 13  # web/src/game/map.ts GRID_R
DIRS = [(dc, dr) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if dc or dr]


def _inside(sk: dict | None, ax: int, ay: int, c: tuple[int, int]) -> bool:
    if sk is None:
        return abs(c[0]) <= LIMIT and abs(c[1]) <= LIMIT
    return 0 <= c[0] + ax < sk["cols"] and 0 <= c[1] + ay < sk["rows"]


def path(
    world, place: str | None, start: tuple[int, int], goal: tuple[int, int], actor_id: str, max_cells: int | None = None
) -> list[tuple[int, int]] | None:
    """Кратчайший путь (без стартовой клетки) от ``start`` до ``goal`` в клетках от строя, или None — не дойти.
    Сквозь других участников путь не идёт: занятые клетки он обходит."""
    sk = grid._sketch(world, place)
    ax, ay = grid.anchor(world, place, sk)
    if start != goal and (not _inside(sk, ax, ay, goal) or grid.cell_problem(world, place, goal, actor_id, sk)):
        return None
    return search(world, place, start, lambda c: c == goal, actor_id, max_cells, sk)


def search(
    world,
    place: str | None,
    start: tuple[int, int],
    done: Callable[[tuple[int, int]], bool],
    actor_id: str,
    max_cells: int | None = None,
    sk: dict | None = None,
) -> list[tuple[int, int]] | None:
    """Поиск в ширину по свободным клеткам до первой, где ``done``; путь без стартовой клетки."""
    sk = sk if sk is not None else grid._sketch(world, place)
    ax, ay = grid.anchor(world, place, sk)
    if done(start):
        return []
    free: dict[tuple[int, int], bool] = {}

    def ok(c: tuple[int, int]) -> bool:
        if c not in free:
            free[c] = _inside(sk, ax, ay, c) and grid.cell_problem(world, place, c, actor_id, sk) is None
        return free[c]

    prev: dict[tuple[int, int], tuple[int, int]] = {start: start}
    q = deque([(start, 0)])
    while q:
        cur, d = q.popleft()
        if max_cells is not None and d >= max_cells:
            continue
        for dc, dr in DIRS:
            nxt = (cur[0] + dc, cur[1] + dr)
            if nxt in prev or not ok(nxt):
                continue
            prev[nxt] = cur
            if done(nxt):
                out = [nxt]
                while prev[out[-1]] != start:
                    out.append(prev[out[-1]])
                return out[::-1]
            q.append((nxt, d + 1))
    return None


def beside(
    world, place: str | None, start: tuple[int, int], targets: list[tuple[int, int]], actor_id: str, max_cells=None
) -> list[tuple[int, int]] | None:
    """Путь к ближайшей свободной клетке рядом с целью (существо, предмет эскиза, выход за краем)."""
    aims = set(targets)
    return search(world, place, start, lambda c: c not in aims and any(_near(c, t) for t in aims), actor_id, max_cells)


def cell_of(world, actor_id: str) -> tuple[int, int]:
    p = grid.pos_of(world, actor_id)
    if p.cell is not None:
        return p.cell
    return (0, 0) if p.zone is None else grid.cell_from_zone(p)


def _near(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 1


def provokers(world, place: str | None, start: tuple[int, int], route: list[tuple[int, int]]) -> list[Any]:
    """Враждебные существа, из досягаемости которых (соседняя клетка) герой уходит по этому пути, в порядке ухода."""
    out: list[Any] = []
    cells = [start, *route]
    foes = [
        e
        for e in world.entities.values()
        if e.kind == "creature"
        and e.location_id == place
        and not (e.state or {}).get("dead")
        and not (e.state or {}).get("fled")
        and (e.state or {}).get("attitude", "hostile") == "hostile"
        and grid.pos_of(world, e.id).cell is not None
    ]
    for a, b in zip(cells, cells[1:], strict=False):
        for e in foes:
            c = grid.pos_of(world, e.id).cell
            if e not in out and _near(a, c) and not _near(b, c):
                out.append(e)
    return out


def toward(world, place: str | None, actor_id: str, target_id: str, max_cells: int) -> list[tuple[int, int]] | None:
    """Путь существа к соседней с целью клетке, обрезанный скоростью; None — подойти нельзя."""
    route = beside(world, place, cell_of(world, actor_id), [cell_of(world, target_id)], actor_id)
    return route[:max_cells] if route else None
