"""Формы участка (спецификация 2026-10-12, §3.3): маска пола из сохранённого замысла и seed.

Форму задают физические клетки пола, а не название. Пещера — ограниченный детерминированный вариант неправильного
контура: эллипс, у которого по seed выщерблен край, без разрыва пола и без потери клеток у проходов (``keep``).
"""

from __future__ import annotations

import random
from collections import deque

Cell = tuple[int, int]
NEIGHBOURS = ((1, 0), (-1, 0), (0, 1), (0, -1))
INWARD = {"n": (0, 1), "s": (0, -1), "w": (1, 0), "e": (-1, 0)}
CAVE_EROSION = 0.35


def floor(shape: str, cols: int, rows: int, seed: int, keep: frozenset[Cell] = frozenset()) -> set[Cell]:
    full = {(c, r) for c in range(cols) for r in range(rows)}
    if shape in ("rect", "corridor", "open"):
        return full
    if shape == "circle":
        return _ellipse(cols, rows)
    if shape == "l_shape":
        return {(c, r) for c, r in full if not (c >= cols // 2 and r < rows // 2)}
    if shape == "cave":
        return _cave(cols, rows, seed, keep & full)
    raise ValueError(f"неизвестная форма {shape}")


def inner_cell(floor_: set[Cell], cols: int, rows: int, side: str, at: int) -> Cell | None:
    """Первая клетка пола от края внутрь участка: у неправильной формы пол может отступать от рамки."""
    dc, dr = INWARD[side]
    c, r = {"n": (at, 0), "s": (at, rows - 1), "w": (0, at), "e": (cols - 1, at)}[side]
    while 0 <= c < cols and 0 <= r < rows:
        if (c, r) in floor_:
            return c, r
        c, r = c + dc, r + dr
    return None


def _ellipse(cols: int, rows: int) -> set[Cell]:
    a, b = cols / 2, rows / 2
    return {
        (c, r) for c in range(cols) for r in range(rows) if ((c + 0.5 - a) / a) ** 2 + ((r + 0.5 - b) / b) ** 2 <= 1.0
    }


def _cave(cols: int, rows: int, seed: int, keep: frozenset[Cell]) -> set[Cell]:
    cells = _ellipse(cols, rows) | set(keep)
    rng = random.Random(seed)
    edge = sorted(c for c in cells if any((c[0] + dc, c[1] + dr) not in cells for dc, dr in NEIGHBOURS))
    for cell in edge:
        if cell in keep or rng.random() >= CAVE_EROSION:
            continue
        trial = cells - {cell}
        if _connected(trial):
            cells = trial
    return cells


def _connected(cells: set[Cell]) -> bool:
    if not cells:
        return False
    start = min(cells)
    seen = {start}
    q = deque([start])
    while q:
        c, r = q.popleft()
        for dc, dr in NEIGHBOURS:
            n = (c + dc, r + dr)
            if n in cells and n not in seen:
                seen.add(n)
                q.append(n)
    return len(seen) == len(cells)
