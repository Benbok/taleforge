# Постепенная генерация локаций, поставка 1: blueprint, геометрия и переходы — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Комплекс связанных участков (храм из 6 помещений и поле с дорогой, ручьём и мостом) строится из
структурированного замысла детерминированным provider, хранится как версионированный blueprint, превращается кодом
в эскизы участков с единой маской пола и проходит серверными переходами «сначала подготовить, потом войти».

**Architecture:** Новый пакет `app/core/layout/` — чистые данные (`contracts`, `intent`), формы (`shapes`), проверка
(`validation`), построение эскиза участка (`geometry`), детерминированный provider (`provider`), хранение в мире
(`store`), исполнители фаз (`executor`), размещение обстановки (`furnish`) и переход (`transit`). Фазы
`location_layout` и `location_geometry` встают в существующий механизм `WorldGenerationState` (lease, CAS, ревизии).
Геометрия публикуется в привычный `state.sketch` участка, поэтому движение, досягаемость и карта продолжают читать
один формат; новая маска пола становится общей мерой непроходимости для шага, пути, прямой видимости и проверки.

**Tech Stack:** Python 3.12, SQLAlchemy 2 async, Alembic, Pydantic 2, pytest (SQLite по умолчанию), ruff (120).

**Spec:** `docs/superpowers/specs/2026-10-12-generative-location-maps-design.md` — §9 делит работу на три поставки,
этот план — первая. Поставки 2 (SVG-композиция, индивидуальная память карты) и 3 (архитектор, текстовый provider,
первая сцена, подготовка вперёд, учёт расходов) получают свои планы после этой.

## Global Constraints

- Клетка — 5 футов; сторона участка не больше 30 клеток (`sketch.MAX_SIDE`).
- В комплексе 1–12 участков (типично 4–8); не больше 8 проходов на участок. Больше — следующий комплекс.
- Поворотов участков нет: ориентация север/восток общая, смещение участка на плане уровня — целые клетки.
- Геометрия строится кодом из blueprint и seed, без LLM-вызова. Модель (поставка 3) не выдаёт SVG, ORM-состояние или код.
- Blueprint — неизменный замысел; текущее состояние прохода живёт в `state.passages` корня, вещей — в сущностях.
- Реальные id участков назначает сервер; `area_ref` и `passage_ref` — стабильные локальные ссылки blueprint.
- Готовые приключения и старые эскизы без маски ведут себя как раньше; книжные карты не пересобираются.
- Трава и вода — визуальное поле: никаких новых механик скорости, плавания или урона.
- Диагональный шаг сквозь стык двух непроходимых клеток запрещён — и для стен, и для клеток вне маски.
- Сетевые вызовы не держат транзакцию БД; lease, CAS, ревизии и запрет дубликатов сохраняются.
- Тайный проход не раскрывается игроку ни в эскизе, ни в соседстве мест, ни в тексте ошибки.
- Комментарии, docstring и тексты для игрока — по-русски, в стиле окружающего кода; ruff `line-length = 120`.
- Не трогать и не коммитить чужие изменения рабочей копии: `docs/README.md`, неотслеживаемые спеки.

**Вне этой поставки:** SVG-слои, узоры материалов и `MapWindow`; память карты и раскрытие по героям (сейчас — прежние
`visited_by` и общий флаг `hidden` прохода); текстовый provider структуры и лимит его вызовов; интеграция с
`architect`/`develop`; подготовка первой сцены; подготовка вперёд; учёт суммарной стоимости; дальние ориентиры.

## Review Focus

1. **Старые эскизы и комнаты книги.** Эскиз без `mask`, `width` и `cells` у выходов ведёт себя побайтно как раньше:
   те же ошибки шага, те же клетки выходов. Тест — Task 1 (`test_legacy_sketch_reads_exactly_as_before`) и прогон
   `tests/test_sketch.py tests/test_grid.py tests/test_world_objects_reach.py tests/test_adventure.py` в Task 13.
2. **Мир изменился между подготовкой и переходом.** Дверь закрыли или герой ушёл, пока готовился участок: переход не
   происходит, готовый участок остаётся. Тест — Task 11 (`test_door_closed_during_preparation_keeps_area_but_not_hero`).
3. **Двойная подготовка.** Два исполнителя или повторный `prepare_complex` дают один blueprint и один набор участков.
   Тест — Task 7 (`test_concurrent_layout_makes_one_blueprint`, `test_layout_publishes_areas_once`).
4. **Утечка тайного.** Тайный проход, его `passage_ref` и тайный участок не видны игроку на схеме и в соседстве мест,
   а попытка пройти тайным ходом отвечает так же, как несуществующим. Тесты — Task 9
   (`test_player_map_hides_secret_passage_and_area`) и Task 11 (`test_hidden_passage_reads_as_missing`).
5. **Ручной эскиз мастера.** Эскиз, нарисованный мастером на участке, не перезаписывают ни фаза геометрии, ни
   техническая модель `surveyor`. Тесты — Task 7 (`test_geometry_builds_sketch_and_keeps_manual`) и Task 8
   (`test_surveyor_and_redraw_do_not_replace_blueprint_sketch`).

---

## Карта файлов

| Файл | Ответственность |
| --- | --- |
| `app/core/sketch.py` (изм.) | маска пола, `solid_cells`, `exit_cells`, ширина выхода, живое состояние проходов, ключи проекции |
| `app/core/positions.py`, `app/core/steps.py`, `app/core/reach.py` (изм.) | одна мера непроходимости: стены ∪ вне маски |
| `app/core/layout/__init__.py` | оглавление пакета |
| `app/core/layout/contracts.py` | dataclass blueprint, константы, геометрические примитивы, JSON |
| `app/core/layout/shapes.py` | маски форм: прямоугольник, круг, Г, коридор, открытый участок, пещера; клетка у прохода |
| `app/core/layout/geometry.py` | эскиз участка из blueprint + проверка связности |
| `app/core/layout/validation.py` | лимиты, стыки, края, рельеф на стыках, достижимость, обязательства |
| `app/core/layout/intent.py` | Pydantic-замысел комплекса (вход инструмента и provider) |
| `app/core/layout/provider.py` | детерминированный provider и упрощённый fallback |
| `app/core/layout/store.py` | комплекс в мире: корень, участки, живые проходы, резервы фаз |
| `app/core/layout/executor.py` | исполнители `location_layout` и `location_geometry` |
| `app/core/layout/furnish.py` | обстановка участка — связанные детали эскиза |
| `app/core/layout/transit.py` | переход: `begin` → подготовка → `finish`; очередь хода |
| `app/core/world_generation/{contracts,storage,service}.py` (изм.) | новые фазы, `commit_with`, зависимости фаз |
| `app/core/plot_anchors.py` (изм.) | зацепки корня следуют за участком blueprint |
| `app/core/topology.py` (изм.) | соседство участков — по проходам, не по вложенности |
| `app/db/models.py`, `alembic/versions/0021_location_layout_phases.py` | CHECK фаз |
| `app/tools/master/generation.py` (изм.) | `prepare_complex` (команда ведущего) |
| `app/tools/master/places.py` (изм.) | `edit_sketch`/`sketch_place` для проходов, `traverse_passage`, геометрия при входе |
| `app/agents/surveyor.py` (изм.) | не трогает эскиз из blueprint |
| `app/agents/master/finish.py`, `app/gateway/ws.py`, `app/gateway/protocol.py` (изм.) | завершение очереди переходов, `map.traverse` |
| `tests/layout_pilot.py` | общие blueprint и пилотный замысел для тестов |
| `tests/test_layout_*.py` | тесты поставки |
| `docs/location-maps-delivery1.md` | итог поставки для следующих планов |

## Общие соглашения тестов

Тесты игры строятся как в `tests/test_world_generation.py`: `party(client, admin)` даёт кампанию и героя,
`_play(settings, cid, fn)` выполняет `fn(ctx)` в транзакции инструментов, `_ok(ctx, name, args)` вызывает инструмент и
требует успеха. Запуск одного теста: `uv run pytest tests/<file>.py::<test> -q`. Если `uv` недоступен, использовать
уже установленное окружение: `python -m pytest ...`.

---

### Task 1: Маска пола и единая мера непроходимости

**Files:**
- Modify: `app/core/sketch.py` (новые функции после `side_len`; `check`; `for_viewer`)
- Modify: `app/core/positions.py:104-143` (`cell_problem`, `floor_problem`), `app/core/positions.py:270-296` (`wall_between`)
- Modify: `app/core/steps.py:422` (`search`)
- Modify: `app/core/reach.py:36-37` (`_walls`), `app/core/reach.py:106-127` (`reach_errors`)
- Test: `tests/test_layout_mask.py`

**Interfaces:**
- Produces: `sketch.encode_mask(floor: set[tuple[int,int]], cols: int, rows: int) -> list[str]`;
  `sketch.floor_cells(sk: dict | None) -> set[tuple[int,int]] | None`; `sketch.solid_cells(sk: dict | None) -> set[tuple[int,int]]`;
  `sketch.exit_cells(sk: dict, x: dict) -> list[tuple[int,int]]`. Эскиз может нести `mask: list[str]` («.» пол, «#» вне),
  выход — `width: int` (по умолчанию 1) и `cells: list[[c, r]]` (клетки у прохода внутри участка).

- [ ] **Step 1: Write the failing tests**

```python
# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Маска пола участка (спецификация 2026-10-12, §3.3): одна мера непроходимости для шага, пути, видимости и карты."""

from app.core import positions as grid
from app.core import reach, sketch, steps
from tests.game import import_base, party
from tests.test_map import _ok, _play
from tests.test_sketch import CELL

RING = {
    "shape": "cave",
    "cols": 5,
    "rows": 5,
    "party": [2, 2],
    "walls": [],
    "mask": ["#...#", ".....", ".....", ".....", "#...#"],
    "exits": [{"name": "Лаз", "side": "w", "at": 2, "kind": "gap", "state": "open"}],
    "features": [],
}


def test_legacy_sketch_reads_exactly_as_before():
    assert sketch.floor_cells(CELL) is None
    assert sketch.solid_cells(CELL) == {(5, 0)}
    assert sketch.exit_cells(CELL, CELL["exits"][0]) == [reach.exit_cell(CELL, CELL["exits"][0])] == [(1, 3)]
    assert sketch.check(CELL, set()) == []
    assert "mask" not in sketch.for_viewer(CELL, False, set())


def test_mask_makes_void_cells_solid():
    assert sketch.solid_cells(RING) == {(0, 0), (4, 0), (0, 4), (4, 4)}
    assert sketch.encode_mask(sketch.floor_cells(RING), 5, 5) == RING["mask"]
    assert sketch.check(RING, set()) == []
    assert sketch.for_viewer(RING, False, set())["mask"] == RING["mask"]


def test_bad_mask_and_feature_on_void_are_errors():
    assert any("маска пола" in e for e in sketch.check({**RING, "mask": ["#..#"]}, set()))
    on_void = {**RING, "features": [{"name": "Сундук", "kind": "object", "cells": [[0, 0, 0, 0]]}]}
    assert any("«Сундук» стоит на стене (0, 0)" in e for e in sketch.check(on_void, set()))
    assert any("отряд" in e for e in sketch.check({**RING, "party": [4, 4]}, set()))


def test_diagonal_between_two_void_cells_is_closed():
    pinch = {"shape": "cave", "cols": 2, "rows": 2, "party": [0, 1], "walls": [], "exits": [], "features": [],
             "mask": ["#.", ".#"]}  # fmt: skip
    assert reach.walk_region(pinch, (0, 1)) == {(0, 1)}


def test_wide_exit_occupies_interval():
    sk = {
        "shape": "open",
        "cols": 6,
        "rows": 4,
        "party": [1, 1],
        "walls": [],
        "features": [],
        "exits": [
            {"name": "Поле", "side": "e", "at": 1, "width": 2, "kind": "gap", "state": "open"},
            {"name": "Калитка", "side": "e", "at": 2, "kind": "gap", "state": "open"},
        ],
    }
    assert any("два выхода в одной клетке стороны восток" in e for e in sketch.check(sk, set()))
    assert sketch.exit_cells(sk, sk["exits"][0]) == [(5, 1), (5, 2)]
    too_wide = {**sk, "exits": [{**sk["exits"][0], "at": 3}]}
    assert any("at от 0 до 2" in e for e in sketch.check(too_wide, set()))
    stored = {**sk["exits"][0], "cells": [[4, 1], [4, 2]]}
    assert sketch.exit_cells(sk, stored) == [(4, 1), (4, 2)]


def test_hero_cannot_step_into_void_or_squeeze_between_void_corners(client, admin, settings):
    import_base(settings)
    c, _, hero = party(client, admin)
    cid, hid = c["id"], hero["id"]

    async def walk(ctx):
        place = (await _ok(ctx, "create_location", {"name": "Грот", "make_current": True}))["location_id"]
        en = ctx.world.entities[place]
        en.state = {
            **(en.state or {}),
            "sketch": {"shape": "cave", "cols": 4, "rows": 3, "party": [0, 0], "walls": [], "exits": [],
                       "features": [], "mask": [".#..", "#...", "...."]},  # fmt: skip
        }
        w = ctx.world
        void = grid.cell_problem(w, place, (1, 0), hid)
        stuck = steps.path(w, place, (0, 0), (2, 1), hid)  # из (0,0) только по диагонали между пустотами
        free = steps.path(w, place, (1, 1), (3, 0), hid)
        return void, stuck, free

    void, stuck, free = _play(settings, cid, walk)
    assert "вне пола" in void
    assert stuck is None
    assert free is not None and free[-1] == (3, 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout_mask.py -q`
Expected: FAIL — `AttributeError: module 'app.core.sketch' has no attribute 'floor_cells'`.

- [ ] **Step 3: Add mask helpers to `app/core/sketch.py`** (сразу после `side_len`; в docstring модуля добавить строку
  `mask: ["..#"], exits[].width, exits[].cells` к описанию формата)

```python
def encode_mask(floor: set[tuple[int, int]], cols: int, rows: int) -> list[str]:
    """Маска пола участка неправильной формы: строка на ряд, «.» — пол, «#» — вне участка."""
    return ["".join("." if (c, r) in floor else "#" for c in range(cols)) for r in range(rows)]


def floor_cells(sk: dict | None) -> set[tuple[int, int]] | None:
    """Клетки пола по маске; None — маски нет, пол — весь прямоугольник (старые эскизы и комнаты книги)."""
    mask = (sk or {}).get("mask")
    if not mask:
        return None
    return {(c, r) for r, row in enumerate(mask) for c, ch in enumerate(row) if ch == "."}


def solid_cells(sk: dict | None) -> set[tuple[int, int]]:
    """Непроходимые клетки рамки: стены и всё вне маски пола. Одна мера для шага, пути, прямой видимости и карты."""
    if not sk:
        return set()
    out = {(int(x[0]), int(x[1])) for x in sk.get("walls") or []}
    floor = floor_cells(sk)
    if floor is not None:
        out |= {(c, r) for c in range(sk["cols"]) for r in range(sk["rows"]) if (c, r) not in floor}
    return out


def exit_cells(sk: dict, x: dict) -> list[tuple[int, int]]:
    """Клетки места у выхода, с которых в него входят. Проход комплекса хранит их сам (маска может отодвинуть пол
    от края); у обычного выхода — клетки края на ширине ``width``."""
    if x.get("cells"):
        return [(int(c[0]), int(c[1])) for c in x["cells"]]
    at, side, width = int(x["at"]), x["side"], int(x.get("width") or 1)
    if side == "n":
        return [(at + i, 0) for i in range(width)]
    if side == "s":
        return [(at + i, sk["rows"] - 1) for i in range(width)]
    if side == "w":
        return [(0, at + i) for i in range(width)]
    return [(sk["cols"] - 1, at + i) for i in range(width)]
```

- [ ] **Step 4: Teach `sketch.check` the mask and exit width**

В начале `check`, сразу после `inside = ...`:

```python
    mask = sk.get("mask")
    if mask is not None and (
        len(mask) != rows or any(len(row) != cols or set(row) - {".", "#"} for row in mask)
    ):
        errors.append(f"маска пола: {rows} строк по {cols} символов «.» или «#»")
        mask = None
    void = (solid_cells({**sk, "walls": []}) if mask is not None else set())
```

В цикле по клеткам детали заменить `if (c, r) in walls:` на `if (c, r) in walls or (c, r) in void:`.

Цикл по выходам заменить целиком:

```python
    seen: set[tuple[str, int]] = set()
    for x in sk.get("exits") or []:
        n = side_len(sk, x["side"])
        width = int(x.get("width") or 1)
        if width < 1 or not 0 <= x["at"] <= n - width:
            errors.append(f"выход «{x['name']}»: at от 0 до {n - width} на стороне {SIDES[x['side']]}")
        cells = {(x["side"], x["at"] + i) for i in range(max(width, 1))}
        if cells & seen:
            errors.append(f"два выхода в одной клетке стороны {SIDES[x['side']]} ({min(a for _, a in cells & seen)})")
        seen |= cells
        if x.get("to") and x["to"] not in place_ids:
            errors.append(f"выход «{x['name']}»: нет места {x['to']}; сначала create_location")
```

Проверку отряда заменить на `elif (c, r) in walls or (c, r) in taken or (c, r) in void:` (текст ошибки прежний).

В `for_viewer` расширить копируемые ключи:

```python
    out = {
        k: sk[k]
        for k in ("shape", "cols", "rows", "party", "walls", "book", "mask", "edges", "terrain", "material", "environment")
        if k in sk
    }
```

- [ ] **Step 5: Route movement through `solid_cells`**

`app/core/positions.py`, `cell_problem` — после проверки стены:

```python
        if [c, r] in (sk.get("walls") or []):
            return f"клетка {shown} — стена"
        from app.core import sketch as sketch_mod

        floor = sketch_mod.floor_cells(sk)
        if floor is not None and (c, r) not in floor:
            return f"клетка {shown} — вне пола места"
```

`floor_problem` — после проверки границ, до проверки стены:

```python
    from app.core import sketch as sketch_mod

    floor = sketch_mod.floor_cells(sk)
    if floor is not None and (c, r) not in floor:
        return f"клетка {[c, r]} — вне пола места"
```

`wall_between` — заменить `walls = {tuple(x) for x in (sk or {}).get("walls") or []}` на:

```python
    from app.core import sketch as sketch_mod

    walls = sketch_mod.solid_cells(sk)
```

`app/core/steps.py`: добавить `from app.core import sketch` к импортам и заменить строку
`walls = {tuple(x) for x in (sk or {}).get("walls") or []}` на `walls = sketch.solid_cells(sk)`.

`app/core/reach.py`:

```python
def _walls(sk: dict) -> set[Cell]:
    from app.core import sketch

    return sketch.solid_cells(sk)
```

и в `reach_errors` цикл по выходам:

```python
    for x in sk.get("exits") or []:
        from app.core import sketch

        cells = [c for c in sketch.exit_cells(sk, x) if _inside(sk, c)]
        if not any(c in baseline for c in cells) or any(c in region for c in cells):
            continue
        cell = next(c for c in cells if c in baseline)
        if cell in taken:
            errors.append(f"«{taken[cell]}» загораживает выход «{x['name']}»")
        else:
            errors.append(f"«{', '.join(f['name'] for f in linked)}» отрезает выход «{x['name']}» от отряда")
```

(`exit_cell` остаётся для прежних вызовов.)

- [ ] **Step 6: Run the new and the neighbouring tests**

Run: `uv run pytest tests/test_layout_mask.py tests/test_sketch.py tests/test_grid.py tests/test_world_objects_reach.py tests/test_world_objects_sketch.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/core/sketch.py app/core/positions.py app/core/steps.py app/core/reach.py tests/test_layout_mask.py
git commit -m "Маска пола участка — общая мера непроходимости шага, пути и видимости

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Контракты blueprint и формы участков

**Files:**
- Create: `app/core/layout/__init__.py`, `app/core/layout/contracts.py`, `app/core/layout/shapes.py`
- Create: `tests/layout_pilot.py`
- Test: `tests/test_layout_blueprint.py`

**Interfaces:**
- Produces (contracts): `Detail`, `Terrain`, `Edge`, `Area`, `End`, `Passage`, `Blueprint` (frozen dataclasses, поля ниже);
  `Blueprint.to_json() -> dict`, `Blueprint.from_json(dict) -> Blueprint` (ошибка — `LayoutError`);
  `Blueprint.area(ref)`, `.passage(ref)`, `.ends_of(area_ref) -> list[tuple[Passage, End]]`, `.other(passage, end) -> End`;
  `LayoutError(errors: list[str])` с полем `.errors`; константы `SCHEMA_VERSION=1`, `BUILDER_VERSION="layout-v1"`,
  `SHAPES`, `ENVIRONMENTS`, `MATERIALS`, `TERRAIN`, `EDGE_MEANINGS`, `PASSAGE_KINDS`, `VERTICAL`, `WIDE_KINDS`,
  `PASSAGE_STATES`, `MAX_AREAS=12`, `MAX_PASSAGES_PER_AREA=8`, `MAX_SIDE=30`, `OPPOSITE`; функции
  `side_len(area, side)`, `boundary_cells(area, side, start, width)`, `outward(side)`, `rect_cells(rects)`,
  `terrain_cells(area, kind)`, `runs(cells)`.
- Produces (shapes): `floor(shape, cols, rows, seed, keep=frozenset()) -> set[Cell]`;
  `inner_cell(floor, cols, rows, side, at) -> Cell | None`.
- Produces (tests): `tests/layout_pilot.py: two_rooms(**over) -> Blueprint`.

- [ ] **Step 1: Create `tests/layout_pilot.py`**

```python
"""Общие blueprint для тестов комплекса (спецификация 2026-10-12): две комнаты за дверью и два поля со стыком."""

from __future__ import annotations

from app.core.layout.contracts import Area, Blueprint, Detail, End, Passage


def two_rooms(**over) -> Blueprint:
    """Зал 6×4 с колонной и келья 4×4 к востоку за закрытой дверью; ворота зала ведут наружу."""
    hall = Area(
        "hall", "entry", "Зал", "Зал", "indoor", "rect", 6, 4, (0, 0),
        details=(Detail("pillar", "Колонна", "cover", ((2, 1, 2, 1),), solid=True),),
    )  # fmt: skip
    cell = Area("cell", "room", "Келья", "Келья", "indoor", "rect", 4, 4, (6, 0))
    door = Passage("p_cell", "door", "Дверь кельи", "Дверь", (End("hall", "e", 2, 1), End("cell", "w", 2, 1)), "closed")
    gate = Passage("in_hall_w", "door", "Ворота", "Ворота", (End("hall", "w", 1, 1), End(place_id="en_outside")))
    return Blueprint(**{"seed": 7, "entry": "hall", "areas": (hall, cell), "passages": (door, gate), **over})
```

- [ ] **Step 2: Write the failing tests** — `tests/test_layout_blueprint.py`

```python
"""Контракты blueprint и формы участков (спецификация 2026-10-12, §3.3, §4)."""

import json

import pytest

from app.core.layout import shapes
from app.core.layout.contracts import Blueprint, LayoutError, boundary_cells, runs
from tests.layout_pilot import two_rooms


def test_blueprint_json_round_trip_and_version():
    bp = two_rooms()
    data = bp.to_json()
    assert json.loads(json.dumps(data)) == data
    assert Blueprint.from_json(data) == bp
    with pytest.raises(LayoutError):
        Blueprint.from_json({**data, "schema_version": 2})
    with pytest.raises(LayoutError):
        Blueprint.from_json({"seed": 1})
    door = bp.passage("p_cell")
    assert bp.other(door, door.ends[0]).area_ref == "cell"
    assert [p.passage_ref for p, _ in bp.ends_of("hall")] == ["p_cell", "in_hall_w"]


def test_boundary_and_runs():
    hall = two_rooms().area("hall")
    assert boundary_cells(hall, "e", 1, 2) == [(5, 1), (5, 2)]
    assert boundary_cells(hall, "n", 0, 2) == [(0, 0), (1, 0)]
    assert runs({(0, 0), (1, 0), (3, 0), (2, 1)}) == [(0, 0, 1, 0), (3, 0, 3, 0), (2, 1, 2, 1)]


def test_shapes_are_deterministic_masks():
    assert shapes.floor("rect", 3, 2, 0) == {(c, r) for c in range(3) for r in range(2)}
    ell = shapes.floor("l_shape", 4, 4, 0)
    assert (3, 0) not in ell and (0, 0) in ell and (3, 3) in ell and len(ell) == 12
    circle = shapes.floor("circle", 7, 7, 0)
    assert (0, 0) not in circle and (3, 3) in circle and (0, 3) in circle
    keep = frozenset({(0, 4)})
    cave = shapes.floor("cave", 10, 8, 5, keep)
    assert cave == shapes.floor("cave", 10, 8, 5, keep) and (0, 4) in cave
    assert cave <= shapes.floor("circle", 10, 8, 5)
    with pytest.raises(ValueError):
        shapes.floor("star", 3, 3, 0)


def test_inner_cell_walks_inward_to_floor():
    ell = shapes.floor("l_shape", 4, 4, 0)
    assert shapes.inner_cell(ell, 4, 4, "n", 3) == (3, 2)
    assert shapes.inner_cell(ell, 4, 4, "w", 1) == (0, 1)
    assert shapes.inner_cell(set(), 4, 4, "e", 0) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout_blueprint.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.layout'`.

- [ ] **Step 4: Create `app/core/layout/__init__.py`**

```python
"""Постепенная генерация локаций (спецификация 2026-10-12): комплекс участков, его геометрия и переходы.

- ``contracts`` — blueprint и геометрические примитивы, без ORM;
- ``shapes`` — маски форм участка;
- ``geometry`` — эскиз участка из blueprint и проверка связности;
- ``validation`` — проверка blueprint до публикации;
- ``intent`` / ``provider`` — замысел комплекса и детерминированный provider;
- ``store`` — комплекс в мире и резервы фаз;
- ``executor`` — фазы ``location_layout`` и ``location_geometry``;
- ``furnish`` — обстановка на геометрии участка;
- ``transit`` — переход между участками.
"""
```

- [ ] **Step 5: Create `app/core/layout/contracts.py`**

```python
"""Blueprint комплекса (спецификация 2026-10-12, §3.2, §4): участки, проходы, края и сюжетные обязательства.

Чистые данные без ORM: provider предлагает, сервер проверяет (``validation``) и хранит JSON в ``state.blueprint``
корневого места. Координаты участка — локальные, от северо-западного угла: столбцы на восток, строки на юг.
``offset`` — целочисленный сдвиг участка на общем плане уровня; поворотов нет. Blueprint — неизменный замысел:
текущее состояние прохода живёт в ``state.passages`` корня, а вещей — в сущностях мира.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1
BUILDER_VERSION = "layout-v1"
SHAPES = ("rect", "circle", "l_shape", "corridor", "open", "cave")
ENVIRONMENTS = ("indoor", "outdoor")
MATERIALS = ("stone", "earth", "grass", "water", "wood")
TERRAIN = ("road", "path", "stream", "bridge")
EDGE_MEANINGS = ("obstacle", "continuation", "boundary")
PASSAGE_KINDS = ("door", "gate", "arch", "passage", "stairs", "hatch", "gap", "edge")
VERTICAL = ("stairs", "hatch")
WIDE_KINDS = ("edge", "gap", "arch", "gate")
PASSAGE_STATES = ("open", "closed", "locked")
MAX_AREAS = 12
MAX_PASSAGES_PER_AREA = 8
MAX_SIDE = 30  # как app/core/sketch.py MAX_SIDE
OPPOSITE = {"n": "s", "s": "n", "e": "w", "w": "e"}

Cell = tuple[int, int]
Rect = tuple[int, int, int, int]


class LayoutError(Exception):
    """Blueprint или замысел нельзя опубликовать; ``errors`` — что исправить."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Detail:
    detail_ref: str
    name: str
    kind: str  # app/core/sketch.py FEATURE_KINDS
    cells: tuple[Rect, ...]
    solid: bool = False  # колонна, валун: геометрия (непроходимая клетка), а не предмет
    hidden: bool = False


@dataclass(frozen=True)
class Terrain:
    kind: str  # TERRAIN: визуальное поле, механики не меняет
    cells: tuple[Rect, ...]


@dataclass(frozen=True)
class Edge:
    """Смысл отрезка границы открытого участка: препятствие, продолжение местности или граница комплекса."""

    side: str
    start: int
    length: int
    meaning: str


@dataclass(frozen=True)
class Area:
    area_ref: str
    role: str
    name: str  # для мастера
    public_name: str  # что видят герои
    environment: str
    shape: str
    cols: int
    rows: int
    offset: Cell = (0, 0)
    level: int = 0
    material: str = "stone"
    description: str = ""
    secret: bool = False
    details: tuple[Detail, ...] = ()
    terrain: tuple[Terrain, ...] = ()
    edges: tuple[Edge, ...] = ()


@dataclass(frozen=True)
class End:
    """Конец прохода: интервал на стороне участка или место вне комплекса (``place_id``; сам корень — «снаружи»)."""

    area_ref: str | None = None
    side: str | None = None
    start: int = 0
    width: int = 1
    place_id: str | None = None

    @property
    def external(self) -> bool:
        return self.area_ref is None


@dataclass(frozen=True)
class Passage:
    passage_ref: str
    kind: str
    name: str
    public_name: str
    ends: tuple[End, End]
    state: str = "open"
    hidden: bool = False


@dataclass(frozen=True)
class Blueprint:
    seed: int
    entry: str
    areas: tuple[Area, ...]
    passages: tuple[Passage, ...]
    anchors: dict[str, str] = field(default_factory=dict)  # anchor_id зацепки → area_ref
    required: tuple[str, ...] = ()  # участки, к которым обязан вести не тайный путь
    plot_id: str | None = None
    revision: int = 1
    schema_version: int = SCHEMA_VERSION
    builder_version: str = BUILDER_VERSION

    def area(self, ref: str | None) -> Area | None:
        return next((a for a in self.areas if a.area_ref == ref), None)

    def passage(self, ref: str) -> Passage | None:
        return next((p for p in self.passages if p.passage_ref == ref), None)

    def ends_of(self, area_ref: str) -> list[tuple[Passage, End]]:
        return [(p, x) for p in self.passages for x in p.ends if x.area_ref == area_ref]

    def other(self, passage: Passage, end: End) -> End:
        return passage.ends[1] if passage.ends[0] == end else passage.ends[0]

    def to_json(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))  # кортежи → списки, как в JSON-колонке

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Blueprint:
        if not isinstance(d, dict) or int(d.get("schema_version") or 0) != SCHEMA_VERSION:
            raise LayoutError([f"blueprint: неизвестная версия схемы {(d or {}).get('schema_version')}"])
        try:
            return cls._parse(d)
        except (KeyError, TypeError, ValueError, IndexError) as e:
            raise LayoutError([f"blueprint: {type(e).__name__}: {e}"]) from e

    @classmethod
    def _parse(cls, d: dict[str, Any]) -> Blueprint:
        def rects(xs) -> tuple[Rect, ...]:
            return tuple(tuple(int(v) for v in x) for x in xs or ())  # type: ignore[misc]

        def end(e: dict) -> End:
            return End(e.get("area_ref"), e.get("side"), int(e.get("start") or 0), int(e.get("width") or 1),
                       e.get("place_id"))  # fmt: skip

        areas = tuple(
            Area(
                area_ref=a["area_ref"],
                role=a.get("role") or "",
                name=a["name"],
                public_name=a.get("public_name") or a["name"],
                environment=a.get("environment") or "indoor",
                shape=a.get("shape") or "rect",
                cols=int(a["cols"]),
                rows=int(a["rows"]),
                offset=(int(a["offset"][0]), int(a["offset"][1])) if a.get("offset") else (0, 0),
                level=int(a.get("level") or 0),
                material=a.get("material") or "stone",
                description=a.get("description") or "",
                secret=bool(a.get("secret")),
                details=tuple(
                    Detail(x["detail_ref"], x["name"], x.get("kind") or "object", rects(x["cells"]),
                           bool(x.get("solid")), bool(x.get("hidden")))  # fmt: skip
                    for x in a.get("details") or ()
                ),
                terrain=tuple(Terrain(x["kind"], rects(x["cells"])) for x in a.get("terrain") or ()),
                edges=tuple(
                    Edge(x["side"], int(x["start"]), int(x["length"]), x["meaning"]) for x in a.get("edges") or ()
                ),
            )
            for a in d["areas"]
        )
        passages = tuple(
            Passage(
                p["passage_ref"], p["kind"], p["name"], p.get("public_name") or p["name"],
                (end(p["ends"][0]), end(p["ends"][1])), p.get("state") or "open", bool(p.get("hidden")),
            )  # fmt: skip
            for p in d["passages"]
        )
        return cls(
            seed=int(d["seed"]),
            entry=d["entry"],
            areas=areas,
            passages=passages,
            anchors={str(k): str(v) for k, v in (d.get("anchors") or {}).items()},
            required=tuple(d.get("required") or ()),
            plot_id=d.get("plot_id"),
            revision=int(d.get("revision") or 1),
            builder_version=d.get("builder_version") or BUILDER_VERSION,
        )


# --- геометрические примитивы ---


def side_len(area: Area, side: str) -> int:
    return area.cols if side in ("n", "s") else area.rows


def boundary_cells(area: Area, side: str, start: int, width: int) -> list[Cell]:
    """Внутренний ряд клеток участка вдоль стороны на интервале [start, start + width)."""
    if side == "n":
        return [(start + i, 0) for i in range(width)]
    if side == "s":
        return [(start + i, area.rows - 1) for i in range(width)]
    if side == "w":
        return [(0, start + i) for i in range(width)]
    return [(area.cols - 1, start + i) for i in range(width)]


def outward(side: str) -> Cell:
    return {"n": (0, -1), "s": (0, 1), "w": (-1, 0), "e": (1, 0)}[side]


def rect_cells(rects) -> set[Cell]:
    return {(c, r) for c0, r0, c1, r1 in rects for c in range(c0, c1 + 1) for r in range(r0, r1 + 1)}


def terrain_cells(area: Area, kind: str) -> set[Cell]:
    out: set[Cell] = set()
    for t in area.terrain:
        if t.kind == kind:
            out |= rect_cells(t.cells)
    return out


def runs(cells: set[Cell]) -> list[Rect]:
    """Клетки → прямоугольники-отрезки по рядам: компактная запись рельефа."""
    out: list[Rect] = []
    for r in sorted({r for _, r in cells}):
        cs = sorted(c for c, rr in cells if rr == r)
        start = prev = cs[0]
        for c in cs[1:]:
            if c != prev + 1:
                out.append((start, r, prev, r))
                start = c
            prev = c
        out.append((start, r, prev, r))
    return out
```

- [ ] **Step 6: Create `app/core/layout/shapes.py`**

```python
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
        (c, r)
        for c in range(cols)
        for r in range(rows)
        if ((c + 0.5 - a) / a) ** 2 + ((r + 0.5 - b) / b) ** 2 <= 1.0
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
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout_blueprint.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/core/layout/__init__.py app/core/layout/contracts.py app/core/layout/shapes.py tests/layout_pilot.py tests/test_layout_blueprint.py
git commit -m "Blueprint комплекса и маски форм участка

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Геометрия участка из blueprint

**Files:**
- Create: `app/core/layout/geometry.py`
- Test: `tests/test_layout_geometry.py`

**Interfaces:**
- Consumes: Task 1 `sketch.encode_mask/check`, `reach.walk_region/blocked_cells`; Task 2 contracts, `shapes`.
- Produces: `GeometryError(LayoutError)`; `area_seed(seed: int, area_ref: str) -> int`;
  `area_floor(bp, area) -> set[Cell]`; `end_cells(floor, area, end) -> list[Cell | None]`;
  `build_area(bp, area, *, root_id: str | None = None, ids: dict[str, str] | None = None) -> dict` — эскиз:
  `{shape, cols, rows, party, walls, exits, features, environment, material, terrain, edges, blueprint, [mask]}`,
  выход: `{name, side, at, width, kind, state, hidden, to, beyond, passage_ref, cells}`,
  `blueprint: {root_id, area_ref, rev}`. `ids`: area_ref → id сущности участка.

- [ ] **Step 1: Write the failing tests**

```python
"""Геометрия участка из blueprint (спецификация 2026-10-12, §3.3): эскиз, маска и связность проходов."""

from dataclasses import replace

import pytest

from app.core import sketch
from app.core.layout.contracts import Area, Blueprint, Detail, End, Passage
from app.core.layout.geometry import GeometryError, build_area
from tests.layout_pilot import two_rooms


def test_build_area_is_a_valid_sketch_with_passage_cells():
    bp = two_rooms()
    ids = {"hall": "en_hall", "cell": "en_cell"}
    sk = build_area(bp, bp.area("hall"), root_id="en_root", ids=ids)
    assert sketch.check(sk, {"en_cell", "en_outside"}) == []
    assert sk == build_area(bp, bp.area("hall"), root_id="en_root", ids=ids)
    assert sk["walls"] == [[2, 1]] and "mask" not in sk and sk["shape"] == "room"
    door = next(x for x in sk["exits"] if x["passage_ref"] == "p_cell")
    assert door["to"] == "en_cell" and door["cells"] == [[5, 2]] and door["state"] == "closed"
    gate = next(x for x in sk["exits"] if x["passage_ref"] == "in_hall_w")
    assert gate["to"] == "en_outside" and sk["party"] == gate["cells"][0] == [0, 1]
    assert sk["blueprint"] == {"root_id": "en_root", "area_ref": "hall", "rev": 1}


def test_solid_detail_on_a_door_is_rejected():
    bp = two_rooms()
    hall = replace(bp.area("hall"), details=(Detail("pillar", "Колонна", "cover", ((5, 2, 5, 2),), solid=True),))
    with pytest.raises(GeometryError) as e:
        build_area(replace(bp, areas=(hall, bp.area("cell"))), hall)
    assert any("загорожен" in m for m in e.value.errors)


def test_rubble_cutting_the_room_is_rejected():
    bp = two_rooms()
    hall = replace(bp.area("hall"), details=(Detail("rubble", "Завал", "nature", ((3, 0, 3, 3),), solid=True),))
    with pytest.raises(GeometryError) as e:
        build_area(replace(bp, areas=(hall, bp.area("cell"))), hall)
    assert any("не пройти от входа" in m for m in e.value.errors)


def test_cave_keeps_passage_cells_and_is_deterministic():
    cave = Area("cave", "room", "Грот", "Грот", "indoor", "cave", 9, 7)
    bp = Blueprint(
        seed=11,
        entry="cave",
        areas=(cave,),
        passages=(
            Passage("in_cave_w", "gap", "Лаз", "Лаз", (End("cave", "w", 3, 1), End(place_id="en_out"))),
            Passage("in_cave_e", "gap", "Щель", "Щель", (End("cave", "e", 3, 1), End(place_id="en_out2"))),
        ),
    )
    a, b = build_area(bp, cave), build_area(bp, cave)
    assert a == b and "mask" in a and a["shape"] == "cave"
    floor = sketch.floor_cells(a)
    assert all(tuple(c) in floor for x in a["exits"] for c in x["cells"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout_geometry.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.layout.geometry'`.

- [ ] **Step 3: Implement `app/core/layout/geometry.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout_geometry.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/layout/geometry.py tests/test_layout_geometry.py
git commit -m "Эскиз участка строится кодом из blueprint и проверяет связность проходов

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Проверка blueprint

**Files:**
- Create: `app/core/layout/validation.py`
- Modify: `tests/layout_pilot.py` (добавить `two_fields`)
- Test: `tests/test_layout_validation.py`

**Interfaces:**
- Consumes: Task 2 contracts; Task 3 `build_area`, `GeometryError`.
- Produces: `validate(bp: Blueprint) -> list[str]` — пустой список означает «можно публиковать»;
  `tests/layout_pilot.py: two_fields(stream_shift: int = 0) -> Blueprint`.

- [ ] **Step 1: Add `two_fields` to `tests/layout_pilot.py`**

К импортам добавить `Edge, Terrain`; в конец файла:

```python
def two_fields(stream_shift: int = 0) -> Blueprint:
    """Два поля 6×6 со свободным краем между ними; дорога и ручей пересекают стык, дорога уходит в деревню."""
    west = Area(
        "west", "field", "Западное поле", "Поле", "outdoor", "open", 6, 6, (0, 0), material="grass",
        terrain=(Terrain("road", ((0, 2, 5, 3),)), Terrain("stream", ((0, 5, 5, 5),))),
        edges=(Edge("n", 0, 6, "obstacle"), Edge("e", 0, 6, "continuation"), Edge("s", 0, 6, "obstacle"),
               Edge("w", 0, 2, "obstacle"), Edge("w", 2, 2, "boundary"), Edge("w", 4, 2, "obstacle")),
    )  # fmt: skip
    row = 5 - stream_shift
    east = Area(
        "east", "field", "Восточное поле", "Луг", "outdoor", "open", 6, 6, (6, 0), material="grass",
        terrain=(Terrain("road", ((0, 2, 5, 3),)), Terrain("stream", ((0, row, 5, row),))),
        edges=(Edge("n", 0, 6, "obstacle"), Edge("e", 0, 6, "obstacle"), Edge("s", 0, 6, "obstacle"),
               Edge("w", 0, 6, "continuation")),
    )  # fmt: skip
    edge = Passage("p_east", "edge", "Луг", "Луг", (End("west", "e", 0, 6), End("east", "w", 0, 6)))
    road = Passage("in_west_w", "edge", "Дорога", "Дорога", (End("west", "w", 2, 2), End(place_id="en_village")))
    return Blueprint(seed=3, entry="west", areas=(west, east), passages=(edge, road))
```

- [ ] **Step 2: Write the failing tests** — `tests/test_layout_validation.py`

```python
"""Проверка blueprint (спецификация 2026-10-12, §3.2, §4, §5): лимиты, стыки, края, достижимость и обязательства."""

from dataclasses import replace

from app.core.layout.contracts import Area, Blueprint, Edge, End
from app.core.layout.validation import validate
from tests.layout_pilot import two_fields, two_rooms


def test_pilots_are_valid():
    assert validate(two_rooms()) == []
    assert validate(two_fields()) == []


def test_misaligned_door_and_overlap():
    bp = two_rooms()
    shifted = replace(bp.area("cell"), offset=(6, 1))
    assert any("не совпадают на плане" in e for e in validate(replace(bp, areas=(bp.area("hall"), shifted))))
    inside = replace(bp.area("cell"), offset=(5, 0))
    assert any("пересекаются" in e for e in validate(replace(bp, areas=(bp.area("hall"), inside))))


def test_limits_and_wide_door():
    many = tuple(Area(f"a{i}", "room", "A", "A", "indoor", "rect", 2, 2, (i * 2, 0)) for i in range(13))
    assert any("от 1 до 12" in e for e in validate(Blueprint(seed=1, entry="a0", areas=many, passages=())))
    bp = two_rooms()
    wide = replace(bp.passage("p_cell"), ends=(End("hall", "e", 1, 2), End("cell", "w", 1, 2)))
    assert any("шире одной клетки" in e for e in validate(replace(bp, passages=(wide, bp.passage("in_hall_w")))))


def test_vertical_passage_needs_two_levels():
    bp = two_rooms()
    stairs = replace(bp.passage("p_cell"), kind="stairs")
    assert any("разные уровни" in e for e in validate(replace(bp, passages=(stairs, bp.passage("in_hall_w")))))


def test_open_edges_must_be_covered_and_match_passages():
    bp = two_fields()
    west = replace(bp.area("west"), edges=bp.area("west").edges[:-1])  # нет отрезка w 4..5
    assert any("без пропусков" in e for e in validate(replace(bp, areas=(west, bp.area("east")))))
    wrong = tuple(Edge(g.side, g.start, g.length, "obstacle") if g.meaning == "continuation" else g
                  for g in bp.area("east").edges)  # fmt: skip
    east = replace(bp.area("east"), edges=wrong)
    assert any("p_east" in e for e in validate(replace(bp, areas=(bp.area("west"), east))))


def test_stream_must_join_across_the_edge():
    errors = validate(two_fields(stream_shift=1))
    assert any("«stream» обрывается" in e for e in errors)


def test_required_area_behind_secret_and_orphans():
    bp = two_rooms(required=("cell",))
    secret = replace(bp.passage("p_cell"), hidden=True)
    errors = validate(replace(bp, passages=(secret, bp.passage("in_hall_w"))))
    assert any("только через тайный проход" in e for e in errors)
    lonely = replace(bp, passages=(bp.passage("in_hall_w"),), required=())
    assert any("cell не связан с входом" in e for e in validate(lonely))
    assert any("нет участка crypt" in e for e in validate(two_rooms(anchors={"relic": "crypt"})))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout_validation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.layout.validation'`.

- [ ] **Step 4: Implement `app/core/layout/validation.py`**

```python
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
                    e.append(f"{a.area_ref}: проход {p.passage_ref} на стороне {side} — нужен край «{want}» точно по нему")
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout_validation.py tests/test_layout_geometry.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/core/layout/validation.py tests/layout_pilot.py tests/test_layout_validation.py
git commit -m "Blueprint проверяется до публикации: стыки, края, рельеф и путь к обязательному

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Замысел комплекса и детерминированный provider

**Files:**
- Create: `app/core/layout/intent.py`, `app/core/layout/provider.py`
- Modify: `tests/layout_pilot.py` (добавить `pilot_intent`)
- Test: `tests/test_layout_provider.py`

**Interfaces:**
- Consumes: Task 2 contracts; Task 4 `validate`.
- Produces: Pydantic `LayoutIntent{schema_version=1, entry, parts: list[PartIntent], approaches: list[ApproachIntent],
  bands: list[BandIntent]}`; `PartIntent{part_ref, role, name, public_name, description, environment, shape, size,
  cols, rows, level, material, connects_to, side, passage_kind, passage_name, passage_state, secret, required,
  anchors, details: list[DetailIntent]}`; `ApproachIntent{part_ref, side, kind, public_name, outside_id, band, width}`;
  `BandIntent{band_ref, kind, axis, at, width, start, end}` (координаты полос — на плане, начало — северо-западный
  угол входного участка). `DeterministicLayoutProvider().propose(intent, *, seed: int, root_id: str,
  plot_id: str | None = None, fallback: bool = False) -> Blueprint` или `LayoutError`. Проходы:
  `p_<part_ref>` — связь части с родителем, `in_<part_ref>_<side>` — подход снаружи.
- Produces (tests): `pilot_intent(outside_id: str = "en_village") -> LayoutIntent`.

- [ ] **Step 1: Add `pilot_intent` to `tests/layout_pilot.py`**

К импортам добавить `from app.core.layout.intent import LayoutIntent`; в конец файла:

```python
def pilot_intent(outside_id: str = "en_village") -> LayoutIntent:
    """Пилот спецификации: поле с дорогой, ручьём и мостом у храма из шести помещений (крипта — уровнем ниже)."""
    pillars = [(1, 2), (6, 2), (1, 6), (6, 6)]
    nave_details = [
        {"detail_ref": f"pillar{i}", "name": "Колонна", "kind": "cover", "cells": [[c, r, c, r]], "solid": True}
        for i, (c, r) in enumerate(pillars)
    ] + [{"detail_ref": "altar", "name": "Алтарь", "kind": "furniture", "cells": [[3, 0, 4, 0]]}]
    return LayoutIntent.model_validate({
        "entry": "road",
        "parts": [
            {"part_ref": "road", "role": "field", "name": "Дорога у храма", "public_name": "Дорога у храма",
             "environment": "outdoor", "shape": "open"},
            {"part_ref": "brook", "role": "field", "name": "Луг у ручья", "public_name": "Луг",
             "environment": "outdoor", "shape": "open", "connects_to": "road", "side": "e", "passage_name": "Луг"},
            {"part_ref": "narthex", "name": "Притвор", "public_name": "Притвор", "cols": 6, "rows": 4,
             "connects_to": "road", "side": "n", "passage_name": "Двери храма", "passage_state": "closed"},
            {"part_ref": "nave", "name": "Неф", "public_name": "Главный зал", "cols": 8, "rows": 10,
             "connects_to": "narthex", "side": "n", "passage_kind": "arch", "passage_name": "Арка",
             "details": nave_details},
            {"part_ref": "chapel", "name": "Часовня реликвии", "public_name": "Часовня", "cols": 5, "rows": 5,
             "connects_to": "nave", "side": "e", "passage_name": "Дверь часовни", "anchors": ["relic"]},
            {"part_ref": "sacristy", "name": "Ризница", "public_name": "Ризница", "cols": 4, "rows": 4,
             "connects_to": "nave", "side": "w", "passage_name": "Низкая дверь"},
            {"part_ref": "vault", "name": "Тайник", "public_name": "Тайник", "cols": 3, "rows": 3,
             "connects_to": "sacristy", "side": "n", "passage_name": "Тайная дверь", "secret": True},
            {"part_ref": "crypt", "name": "Крипта", "public_name": "Крипта", "cols": 8, "rows": 8, "level": -1,
             "connects_to": "nave", "passage_kind": "stairs", "passage_name": "Лестница вниз", "required": True},
        ],
        "approaches": [{"part_ref": "road", "side": "w", "kind": "edge", "public_name": "Дорога в деревню",
                        "outside_id": outside_id, "band": "road"}],
        "bands": [
            {"band_ref": "road", "kind": "road", "axis": "we", "at": 3, "width": 2},
            {"band_ref": "stream", "kind": "stream", "axis": "we", "at": 7},
            {"band_ref": "path", "kind": "path", "axis": "ns", "at": 6, "start": 5, "end": 10},
        ],
    })  # fmt: skip
```

- [ ] **Step 2: Write the failing tests** — `tests/test_layout_provider.py`

```python
"""Детерминированный provider структуры (спецификация 2026-10-12, §3.2, §8): пилот храма и поля, fallback."""

import pytest
from pydantic import ValidationError

from app.core.layout.contracts import End, LayoutError, terrain_cells
from app.core.layout.intent import LayoutIntent
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.layout.validation import validate
from tests.layout_pilot import pilot_intent

ALL = {"road", "brook", "narthex", "nave", "chapel", "sacristy", "vault", "crypt"}


def test_pilot_intent_gives_valid_stable_blueprint():
    p = DeterministicLayoutProvider()
    bp = p.propose(pilot_intent(), seed=42, root_id="en_temple")
    assert validate(bp) == []
    assert p.propose(pilot_intent(), seed=42, root_id="en_temple").to_json() == bp.to_json()
    assert {a.area_ref: a.offset for a in bp.areas} == {
        "road": (0, 0), "brook": (12, 0), "narthex": (3, -4), "nave": (2, -14), "chapel": (10, -12),
        "sacristy": (-2, -11), "vault": (-2, -14), "crypt": (2, -14),
    }  # fmt: skip
    assert bp.area("crypt").level == -1 and bp.passage("p_crypt").kind == "stairs"
    assert bp.passage("p_vault").hidden and bp.area("vault").secret
    assert bp.passage("p_narthex").state == "closed" and len(bp.area("nave").details) == 5
    assert bp.anchors == {"relic": "chapel"} and set(bp.required) == {"chapel", "crypt"}
    edge = bp.passage("p_brook")
    assert edge.kind == "edge" and edge.ends[0].width == 10
    gate = bp.passage("in_road_w")
    assert gate.ends[0] == End("road", "w", 3, 2) and gate.ends[1].place_id == "en_village"


def test_pilot_terrain_joins_and_edges():
    bp = DeterministicLayoutProvider().propose(pilot_intent(), seed=42, root_id="en_temple")
    road, brook = bp.area("road"), bp.area("brook")
    assert terrain_cells(road, "bridge") == {(6, 7)}
    assert {(11, 3), (11, 4)} <= terrain_cells(road, "road") and {(0, 3), (0, 4)} <= terrain_cells(brook, "road")
    assert (11, 7) in terrain_cells(road, "stream") and (0, 7) in terrain_cells(brook, "stream")
    west = [(g.start, g.length, g.meaning) for g in road.edges if g.side == "w"]
    assert west == [(0, 3, "obstacle"), (3, 2, "boundary"), (5, 5, "obstacle")]
    assert [(g.start, g.length, g.meaning) for g in brook.edges if g.side == "w"] == [(0, 10, "continuation")]


def test_fallback_chain_keeps_required_parts_and_anchors():
    bp = DeterministicLayoutProvider().propose(pilot_intent(), seed=42, root_id="en_temple", fallback=True)
    assert validate(bp) == []
    assert {a.area_ref for a in bp.areas} == ALL and bp.anchors == {"relic": "chapel"}
    assert bp.passage("p_vault").hidden


def test_required_secret_part_is_unsatisfiable():
    data = pilot_intent().model_dump()
    data["parts"][-1]["secret"] = True  # обязательная крипта только за тайным ходом
    intent = LayoutIntent.model_validate(data)
    for fallback in (False, True):
        with pytest.raises(LayoutError) as e:
            DeterministicLayoutProvider().propose(intent, seed=1, root_id="en_t", fallback=fallback)
        assert any("тайный проход" in m for m in e.value.errors)


def test_intent_rejects_forward_references_and_unknown_band():
    data = pilot_intent().model_dump()
    data["parts"][1]["connects_to"] = "crypt"
    with pytest.raises(ValidationError):
        LayoutIntent.model_validate(data)
    data = pilot_intent().model_dump()
    data["approaches"][0]["band"] = "river"
    with pytest.raises(ValidationError):
        LayoutIntent.model_validate(data)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout_provider.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.layout.intent'`.

- [ ] **Step 4: Implement `app/core/layout/intent.py`**

```python
"""Пространственный замысел комплекса (спецификация 2026-10-12, §3.1, §3.2): что предлагает ведущий или модель.

Без клеток стен и списка каждого предмета: части с ролью, размером и формой, к какой части примыкает каждая и с
какой стороны, подходы снаружи и сквозные полосы рельефа (дорога, тропа, ручей) в координатах плана, где начало —
северо-западный угол входной части. Обязательные привязки каркаса — ``anchors`` и ``required``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

REF = r"^[a-z][a-z0-9_]{0,31}$"
Side = Literal["n", "e", "s", "w"]


class DetailIntent(BaseModel):
    detail_ref: str = Field(pattern=REF)
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["furniture", "cover", "hazard", "light", "object", "nature"] = "object"
    cells: list[list[int]] = Field(min_length=1, max_length=4, description="[c0, r0, c1, r1] в клетках части")
    solid: bool = Field(False, description="колонна, валун: непроходимая геометрия, не предмет")
    hidden: bool = False


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
    connects_to: str | None = Field(None, description="часть выше по списку; пусто — предыдущая")
    side: Side | None = Field(None, description="с какой стороны родителя примыкает")
    passage_kind: Literal["door", "gate", "arch", "passage", "stairs", "hatch", "gap"] = "door"
    passage_name: str = Field("Проход", min_length=1, max_length=60)
    passage_state: Literal["open", "closed", "locked"] = "open"
    secret: bool = Field(False, description="часть за тайным проходом")
    required: bool = Field(False, description="к части обязан вести не тайный путь")
    anchors: list[str] = Field(default_factory=list, max_length=8, description="зацепки каркаса в этой части")
    details: list[DetailIntent] = Field(default_factory=list, max_length=16)


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
            if p.part_ref == self.entry:
                continue
            if p.connects_to is not None and p.connects_to not in seen:
                raise ValueError(f"{p.part_ref}: connects_to должен ссылаться на часть выше по списку")
            seen.add(p.part_ref)
        bands = {b.band_ref for b in self.bands}
        for a in self.approaches:
            if a.part_ref not in seen:
                raise ValueError(f"подход «{a.public_name}»: нет части {a.part_ref}")
            if a.band is not None and a.band not in bands:
                raise ValueError(f"подход «{a.public_name}»: нет полосы {a.band}")
        return self
```

- [ ] **Step 5: Implement `app/core/layout/provider.py`**

```python
"""Детерминированный provider структуры (спецификация 2026-10-12, §3.2, §8): blueprint из замысла без модели.

Части укладываются по дереву ``connects_to``: ребёнок примыкает к родителю с заданной (или по seed выбранной)
стороны, по центру общей стены, без пересечений на своём уровне; часть другого уровня встаёт под родителем и
соединяется лестницей. Две открытые части соединяет свободный край во всю общую границу. ``fallback`` — упрощённая
цепочка на восток (тайные части — в конце): та же обязательная часть, те же привязки и путь к ним. Дорога, тропа и
ручей рисуются по полосам плана, поэтому на стыках совпадают сами; пересечение воды с дорогой — мост.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

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
    Passage,
    Terrain,
    rect_cells,
    runs,
)
from app.core.layout.intent import ApproachIntent, BandIntent, LayoutIntent, PartIntent
from app.core.layout.validation import validate

SIZES = {
    "indoor": {"small": (4, 4), "medium": (6, 6), "large": (8, 10)},
    "outdoor": {"small": (8, 8), "medium": (12, 10), "large": (16, 12)},
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

        def take(ref: str, side: str, start: int, width: int) -> None:
            taken.setdefault((ref, side), []).append((start, start + width))

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
                if not (_free(p_taken, spot - pbox.along(side), width) and _free(c_taken, spot - box.along(side), width)):
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


def _keepout(ref: str, cols: int, rows: int, passages: list[Passage]) -> set[Cell]:
    """Клетки от края внутрь до середины у каждого прохода: крупная деталь здесь могла бы загородить вход."""
    out: set[Cell] = set()
    for p in passages:
        for x in p.ends:
            if x.area_ref != ref:
                continue
            for i in range(x.width):
                at = x.start + i
                if x.side == "n":
                    out |= {(at, r) for r in range(rows // 2 + 1)}
                elif x.side == "s":
                    out |= {(at, r) for r in range(rows - 1, rows // 2 - 1, -1)}
                elif x.side == "w":
                    out |= {(c, at) for c in range(cols // 2 + 1)}
                else:
                    out |= {(c, at) for c in range(cols - 1, cols // 2 - 1, -1)}
    return out


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
    keep = _keepout(part.part_ref, box.cols, box.rows, passages)
    details = tuple(
        Detail(d.detail_ref, d.name, d.kind, tuple(tuple(r) for r in d.cells), d.solid, d.hidden)  # type: ignore[misc]
        for d in part.details
        if not rect_cells(d.cells) & keep
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
        details=details,
        terrain=tuple(Terrain(k, tuple(runs(cells))) for k, cells in sorted(terrain.items()) if cells),
        edges=_edges(part.part_ref, box, passages) if outdoor else (),
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout_provider.py tests/test_layout_validation.py -q`
Expected: PASS. Если смещения пилота разойдутся с ожидаемыми, сверить формулы `_touching` и середину
`lo + (hi - lo) // 2` с расчётом в тесте (нижнее целое при нечётной разнице размеров), а не подгонять тест.

- [ ] **Step 7: Commit**

```bash
git add app/core/layout/intent.py app/core/layout/provider.py tests/layout_pilot.py tests/test_layout_provider.py
git commit -m "Детерминированный provider раскладывает храм и поле по замыслу, с упрощённой цепочкой как fallback

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Фазы `location_layout`/`location_geometry` и хранение комплекса в мире

**Files:**
- Modify: `app/db/models.py:486` (CHECK фаз), `app/core/world_generation/contracts.py:12` (`PHASES`)
- Create: `alembic/versions/0021_location_layout_phases.py`
- Create: `app/core/layout/store.py`
- Test: `tests/test_layout_store.py`

**Interfaces:**
- Consumes: Task 2 `Blueprint`, `BUILDER_VERSION`; Task 5 `LayoutIntent`; `world_generation.storage.find/activate`.
- Produces (store): `complex_of(entity) -> dict | None` (`{"root_id", "area_ref"}`); `blueprint_of(root) -> Blueprint | None`;
  `area_ids(root) -> dict[str, str]`; `passage_live(root, ref) -> dict`; `root_of(entities, area) -> Entity | None`;
  `layout_seed(campaign_id, root_id) -> int`;
  `async reserve_layout(session, campaign, root, intent) -> WorldGenerationState` (идемпотентно);
  `async reserve_geometry(session, campaign_id, root, area, bp) -> WorldGenerationState` (идемпотентно);
  `async request_geometry(ctx, area) -> str | None` — ref неготовой геометрии участка после активации.
  Состояние корня: `state.blueprint` (JSON), `state.areas` (area_ref → id), `state.passages` (ref → `{state, hidden}`).
  Резерв: layout — `{phase, seed, root_id, plot_id, intent}`; geometry — `{phase, root_id, area_ref, blueprint_rev, seed}`.

- [ ] **Step 1: Write the failing tests** — `tests/test_layout_store.py`

```python
"""Фазы комплекса в механизме подготовки (спецификация 2026-10-12, §8): CHECK, миграция и идемпотентный резерв."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.layout import store
from app.db.models import WorldGenerationState
from tests.game import import_base, party, quiet
from tests.layout_pilot import pilot_intent
from tests.test_map import _ok, _play


def test_sqlite_alembic_layout_phases_upgrade_and_downgrade(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    db_path = tmp_path / "phases.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    def table_sql() -> str:
        with sqlite3.connect(db_path) as db:
            return db.execute("SELECT sql FROM sqlite_master WHERE name = 'world_generation_states'").fetchone()[0]

    command.upgrade(config, "0020")
    assert "location_layout" not in table_sql()
    command.upgrade(config, "0021")
    assert "location_layout" in table_sql() and "location_geometry" in table_sql()
    command.downgrade(config, "0020")
    assert "location_layout" not in table_sql() and "container_contents" in table_sql()


def test_reserve_layout_is_idempotent(client, admin, settings):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    quiet(client)
    cid = campaign["id"]

    async def go(ctx):
        temple = (await _ok(ctx, "create_location", {"name": "Старый храм"}))["location_id"]
        root = ctx.world.entities[temple]
        first = await store.reserve_layout(ctx.session, ctx.campaign, root, pilot_intent())
        again = await store.reserve_layout(ctx.session, ctx.campaign, root, pilot_intent())
        assert first.id == again.id and first.phase == "location_layout" and first.requested_at is None
        assert first.reservation["intent"] == pilot_intent().model_dump(mode="json")
        assert first.seed == store.layout_seed(cid, temple) and 0 <= first.seed < 2**31
        assert store.complex_of(root) is None and store.blueprint_of(root) is None
        return first.id

    ref = _play(settings, cid, go)
    assert isinstance(ref, str) and WorldGenerationState.__tablename__ == "world_generation_states"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout_store.py -q`
Expected: FAIL — `alembic.util.exc.CommandError: Can't locate revision identified by '0021'` и `ModuleNotFoundError ... store`.

- [ ] **Step 3: Extend phases in model and contracts**

`app/db/models.py` (`WorldGenerationState.__table_args__`):

```python
        CheckConstraint(
            "phase IN ('location_initial', 'container_contents', 'location_layout', 'location_geometry')",
            name="ck_world_generation_phase",
        ),
```

`app/core/world_generation/contracts.py`:

```python
PHASES = ("location_initial", "container_contents", "location_layout", "location_geometry")
```

- [ ] **Step 4: Create `alembic/versions/0021_location_layout_phases.py`**

```python
"""Location layout phases: complex structure and area geometry (generative location maps spec, §8).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "phase IN ('location_initial', 'container_contents')"
NEW = "phase IN ('location_initial', 'container_contents', 'location_layout', 'location_geometry')"


def _replace(check: str) -> None:
    with op.batch_alter_table("world_generation_states", recreate="always") as batch:
        batch.drop_constraint("ck_world_generation_phase", type_="check")
        batch.create_check_constraint("ck_world_generation_phase", check)


def upgrade() -> None:
    _replace(NEW)


def downgrade() -> None:
    op.execute("DELETE FROM world_generation_states WHERE phase IN ('location_layout', 'location_geometry')")
    _replace(OLD)
```

Если на SQLite `drop_constraint` падает с `No such constraint: 'ck_world_generation_phase'` (batch не отразил CHECK),
пересоздание таблицы уже теряет старый CHECK: тогда в `_replace` вызывать `drop_constraint` только вне SQLite —
`if op.get_bind().dialect.name != "sqlite": batch.drop_constraint(...)` — и снова прогнать тест миграции.

- [ ] **Step 5: Create `app/core/layout/store.py`**

```python
"""Комплекс в мире (спецификация 2026-10-12, §4): корень хранит blueprint, реальные id участков и живое состояние
проходов; участок знает свой корень и ``area_ref``. Вложенность участка в корень показывает принадлежность, но не
создаёт прохода. Blueprint не источник текущего состояния: открыта ли дверь — ``state.passages`` корня.
"""

from __future__ import annotations

import zlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.layout.contracts import BUILDER_VERSION, Blueprint, LayoutError
from app.core.layout.intent import LayoutIntent
from app.db.models import Campaign, Entity, WorldGenerationState


def _state(e: Any) -> dict:
    return (e.state or {}) if e is not None else {}


def complex_of(e: Any) -> dict | None:
    cx = _state(e).get("complex")
    return cx if isinstance(cx, dict) and cx.get("root_id") and cx.get("area_ref") else None


def blueprint_of(root: Any) -> Blueprint | None:
    raw = _state(root).get("blueprint")
    if not isinstance(raw, dict):
        return None
    try:
        return Blueprint.from_json(raw)
    except LayoutError:
        return None


def area_ids(root: Any) -> dict[str, str]:
    return dict(_state(root).get("areas") or {})


def passage_live(root: Any, ref: str) -> dict:
    return dict((_state(root).get("passages") or {}).get(ref) or {})


def root_of(entities: dict[str, Entity], area: Any) -> Entity | None:
    cx = complex_of(area)
    return entities.get(cx["root_id"]) if cx else None


def layout_seed(campaign_id: str, root_id: str) -> int:
    return zlib.crc32(f"{campaign_id}:{root_id}:layout".encode()) & 0x7FFFFFFF


async def reserve_layout(
    session: AsyncSession, campaign: Campaign, root: Entity, intent: LayoutIntent
) -> WorldGenerationState:
    """Резерв структуры комплекса: замысел и seed фиксируются один раз; повтор возвращает ту же строку."""
    from app.core.world_generation import storage

    row = await storage.find(session, campaign.id, root.id, "location_layout")
    if row is not None:
        return row
    seed = layout_seed(campaign.id, root.id)
    reservation = {
        "phase": "location_layout",
        "seed": seed,
        "root_id": root.id,
        "plot_id": _state(root).get("plot_id"),
        "intent": intent.model_dump(mode="json"),
    }
    row = WorldGenerationState(campaign_id=campaign.id, target_entity_id=root.id, phase="location_layout",
                               status="unprepared", reservation=reservation, seed=seed,
                               generator_version=BUILDER_VERSION)  # fmt: skip
    session.add(row)
    await session.flush()
    return row


async def reserve_geometry(
    session: AsyncSession, campaign_id: str, root: Entity, area: Entity, bp: Blueprint
) -> WorldGenerationState:
    from app.core.world_generation import storage

    row = await storage.find(session, campaign_id, area.id, "location_geometry")
    if row is not None:
        return row
    cx = complex_of(area)
    reservation = {"phase": "location_geometry", "root_id": root.id, "area_ref": cx["area_ref"],
                   "blueprint_rev": bp.revision, "seed": bp.seed}  # fmt: skip
    row = WorldGenerationState(campaign_id=campaign_id, target_entity_id=area.id, phase="location_geometry",
                               status="unprepared", reservation=reservation, seed=bp.seed,
                               generator_version=BUILDER_VERSION)  # fmt: skip
    session.add(row)
    await session.flush()
    return row


async def request_geometry(ctx: Any, area: Any) -> str | None:
    """Участок комплекса без готовой геометрии: запросить её в транзакции команды. Возвращает ref, которого стоит
    дождаться; None — не участок, уже готово или заблокировано (причину читает переход)."""
    from app.core.world_generation import storage

    if complex_of(area) is None:
        return None
    row = await storage.find(ctx.session, ctx.campaign.id, area.id, "location_geometry")
    if row is None or row.status in ("ready", "blocked"):
        return None
    storage.activate(row)
    return row.id
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout_store.py tests/test_world_objects.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/db/models.py app/core/world_generation/contracts.py alembic/versions/0021_location_layout_phases.py app/core/layout/store.py tests/test_layout_store.py
git commit -m "Фазы структуры и геометрии комплекса в механизме подготовки мира

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Исполнители фаз и команда `prepare_complex`

**Files:**
- Create: `app/core/layout/executor.py`
- Modify: `app/core/world_generation/storage.py` (`_own`, `_finish`, `commit_with`, `phase_of`; `commit_result` на них)
- Modify: `app/core/world_generation/service.py` (`Orchestrator.__init__`, `prepare`, `_run`, `_dependencies`)
- Modify: `app/tools/master/generation.py` (`prepare_complex`, `HOST_TOOLS`)
- Test: `tests/test_layout_preparation.py`

**Interfaces:**
- Consumes: Task 3 `build_area`, `GeometryError`; Task 5 provider; Task 6 store.
- Produces: `storage.commit_with(maker, dice_factory, claim, apply, *, quality="normal") -> dict` где
  `apply: Callable[[ToolContext, WorldGenerationState], Awaitable[dict]]` возвращает manifest;
  `storage.phase_of(maker, ref) -> str | None`; `executor.PHASES`; `executor.run(maker, dice_factory, claim, phase, provider)`;
  `Orchestrator(..., layout_provider=None)`; инструмент `prepare_complex{location_id, intent}` →
  `{location_id, accepted, operation_ref}`. Manifest layout: `{schema_version, phase, areas: {ref: id},
  geometry: {ref: wg_id}, notes}`; manifest geometry: `{schema_version, phase, area_ref, notes}`, ручной эскиз —
  `notes: ["manual_preserved"]`. Причины `blocked`: `unsupported_source`, `layout_unsatisfiable`, `target_missing`,
  `stale_blueprint`, `geometry_invalid`. Событие публикации — `prepare_layout`/`prepare_geometry` (hidden).

- [ ] **Step 1: Write the failing tests** — `tests/test_layout_preparation.py`

```python
# ruff: noqa: F811
"""Подготовка комплекса (спецификация 2026-10-12, §3.2, §8): структура и геометрия фазами подготовки мира."""

import asyncio

from sqlalchemy import select

from app.core import sketch
from app.core.layout import store
from app.core.world_generation import storage
from app.core.world_generation.service import Orchestrator
from app.db.models import Entity, Event, WorldGenerationState
from app.gateway.coordination import InMemoryCoordination
from tests.game import import_base, party, quiet, run
from tests.layout_pilot import pilot_intent
from tests.test_map import _ok, _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry, _prepare, _row, _with_maker  # noqa: F401 — фикстура

WGS = WorldGenerationState


def _complex(settings, cid, mutate=None):
    """Деревня (текущая сцена), храм рядом и принятая подготовка комплекса по пилотному замыслу."""

    async def go(ctx):
        village = (await _ok(ctx, "create_location", {"name": "Деревня", "make_current": True}))["location_id"]
        temple = (await _ok(ctx, "create_location", {"name": "Старый храм", "link_to": [village]}))["location_id"]
        intent = pilot_intent(village).model_dump(mode="json")
        if mutate:
            mutate(intent)
        out = await _ok(ctx, "prepare_complex", {"location_id": temple, "intent": intent})
        return village, temple, out["operation_ref"]

    return _play(settings, cid, go)


def _areas(settings, temple) -> dict[str, Entity]:
    async def go(s):
        found = (await s.scalars(select(Entity).where(Entity.location_id == temple))).all()
        return {store.complex_of(e)["area_ref"]: e for e in found if store.complex_of(e)}

    return run(settings, go)


def _activate(settings, cid, area_id) -> str:
    async def go(s):
        row = await storage.find(s, cid, area_id, "location_geometry")
        storage.activate(row)
        await s.commit()
        return row.id

    return run(settings, go)


def _setup(client, admin, settings):
    import_base(settings)
    campaign, heads, hero = party(client, admin)
    quiet(client)
    return campaign["id"], heads, hero["id"]


def test_layout_publishes_areas_once(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    _village, temple, ref = _complex(settings, cid)
    assert _prepare(settings, cid, ref) == "ready"
    areas = _areas(settings, temple)
    assert set(areas) == {"road", "brook", "narthex", "nave", "chapel", "sacristy", "vault", "crypt"}
    assert areas["vault"].state.get("secret") and areas["road"].name == "Дорога у храма"
    root = run(settings, lambda s: s.get(Entity, temple))
    assert store.blueprint_of(root).entry == "road" and store.area_ids(root) == {k: v.id for k, v in areas.items()}
    assert store.passage_live(root, "p_narthex") == {"state": "closed", "hidden": False}
    geometry = rows(settings, WGS, WGS.phase == "location_geometry")
    assert len(geometry) == 8 and all(g.status == "unprepared" and g.requested_at is None for g in geometry)
    assert _row(settings, ref).result_manifest["areas"] == {k: v.id for k, v in areas.items()}
    assert _prepare(settings, cid, ref) == "ready"

    async def again(ctx):
        return await _ok(ctx, "prepare_complex", {"location_id": temple,
                                                 "intent": pilot_intent(_village).model_dump(mode="json")})  # fmt: skip

    assert _play(settings, cid, again)["operation_ref"] == ref
    assert len(_areas(settings, temple)) == 8 and len(rows(settings, Event, Event.tool == "prepare_layout")) == 1


def test_concurrent_layout_makes_one_blueprint(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    _village, temple, ref = _complex(settings, cid)

    async def both(maker):
        a, b = Orchestrator(InMemoryCoordination()), Orchestrator(InMemoryCoordination())
        return await asyncio.gather(a.prepare(maker, cid, ref), b.prepare(maker, cid, ref))

    outcomes = _with_maker(settings, both)
    assert "ready" in outcomes and set(outcomes) <= {"ready", "leased"}
    assert len(_areas(settings, temple)) == 8


def test_geometry_builds_sketch_and_keeps_manual(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    _village, temple, ref = _complex(settings, cid)
    _prepare(settings, cid, ref)
    areas = _areas(settings, temple)
    road_ref = _activate(settings, cid, areas["road"].id)
    assert _prepare(settings, cid, road_ref) == "ready"
    road = run(settings, lambda s: s.get(Entity, areas["road"].id))
    sk = road.state["sketch"]
    assert sk["blueprint"]["area_ref"] == "road" and sk["shape"] == "open" and sk["edges"]
    assert {x["passage_ref"] for x in sk["exits"]} == {"in_road_w", "p_brook", "p_narthex"}

    manual = {"shape": "room", "cols": 6, "rows": 4, "party": [3, 3], "walls": [], "exits": [], "features": []}

    async def draw(ctx):
        await _ok(ctx, "sketch_place", {**manual, "location_id": areas["narthex"].id})

    _play(settings, cid, draw)
    narthex_ref = _activate(settings, cid, areas["narthex"].id)
    assert _prepare(settings, cid, narthex_ref) == "ready"
    assert _row(settings, narthex_ref).result_manifest["notes"] == ["manual_preserved"]
    narthex = run(settings, lambda s: s.get(Entity, areas["narthex"].id))
    assert "blueprint" not in narthex.state["sketch"] and narthex.state["sketch"]["party"] == [3, 3]


def test_unsatisfiable_layout_blocks_without_areas(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)

    def secret_crypt(intent):
        intent["parts"][-1]["secret"] = True

    _village, temple, ref = _complex(settings, cid, secret_crypt)
    assert _prepare(settings, cid, ref) == "blocked"
    assert _row(settings, ref).last_error == "layout_unsatisfiable"
    assert _areas(settings, temple) == {}


def test_location_initial_of_area_waits_for_its_geometry(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    _village, temple, ref = _complex(settings, cid)
    _prepare(settings, cid, ref)
    chapel = _areas(settings, temple)["chapel"].id

    async def resolve(ctx):
        return (await _ok(ctx, "resolve_location", {"location_id": chapel, "profile_id": "minimal"}))["operation_ref"]

    initial = _play(settings, cid, resolve)
    assert _prepare(settings, cid, initial) == "ready"
    geometry = run(settings, lambda s: storage.find(s, cid, chapel, "location_geometry"))
    assert geometry.status == "ready" and geometry.completed_at <= _row(settings, initial).completed_at
    chapel_sk = run(settings, lambda s: s.get(Entity, chapel)).state["sketch"]
    assert sketch.check(chapel_sk, {x["to"] for x in chapel_sk["exits"] if x["to"]}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout_preparation.py -q`
Expected: FAIL — `prepare_complex` не найден в реестре инструментов.

- [ ] **Step 3: Extract the ownership prologue and epilogue in `storage.py`**

Добавить перед `commit_result`:

```python
async def _own(s, claim: Claim) -> None:
    """Защищённая запись мира от ревизии снимка и CAS строки по токену: только владелец lease пишет результат."""
    await world_write(s, claim.campaign_id, claim.world_revision)
    if now() >= claim.lease_until:
        raise LeaseLost(claim.ref)
    cas = (
        (WGS.id == claim.ref)
        & (WGS.lease_token == claim.token)
        & (WGS.revision == claim.revision)
        & (WGS.status == "preparing")
    )
    done = await s.execute(update(WGS).where(cas).values(revision=WGS.revision + 1, updated_at=now()))
    if done.rowcount != 1:
        raise LeaseLost(claim.ref)


def _finish(row: WorldGenerationState, manifest: dict[str, Any], quality: str) -> None:
    row.status = "ready"
    row.quality = quality
    row.lease_token = None
    row.lease_until = None
    row.last_error = None
    row.completed_at = now()
    row.result_manifest = manifest
    row.result_digest = digest(manifest)


async def phase_of(maker, ref: str) -> str | None:
    async with maker() as s:
        return await s.scalar(select(WGS.phase).where(WGS.id == ref))


async def commit_with(maker, dice_factory, claim: Claim, apply, *, quality: str = "normal") -> dict[str, Any]:
    """Результат произвольной фазы одной транзакцией по правилам ``commit_result``: ``apply(ctx, row)`` меняет мир и
    возвращает manifest. ``WorldConflict``, ``LeaseLost`` и ``Blocked`` откатывают всё."""
    from app.tools.runtime import open_context

    async with maker() as s:
        campaign = await s.get(Campaign, claim.campaign_id)
        await _own(s, claim)
        ctx = await open_context(s, campaign, dice_factory(), turn_id=None, seat_id=None)
        row = await s.get(WGS, claim.ref)
        manifest = await apply(ctx, row)
        _finish(row, manifest, quality)
        await s.commit()
        return manifest
```

В `commit_result` заменить блок от `await world_write(...)` до `raise LeaseLost(claim.ref)` (после `update`) на
`await _own(s, claim)`, а семь присваиваний `row.status ... row.result_digest` в конце — на `_finish(row, manifest, quality)`.

- [ ] **Step 4: Create `app/core/layout/executor.py`**

```python
"""Исполнители фаз ``location_layout`` и ``location_geometry`` (спецификация 2026-10-12, §3.2, §3.3, §8).

Структура: provider предлагает blueprint из замысла резерва — сначала обычный, затем упрощённый fallback; ни тот, ни
другой не выполнили обязательств — ``blocked``, несогласованный результат не публикуется. Публикация — одна
``world_write``: участки с реальными id, blueprint, живые проходы и резервы геометрии всех участков (не запрошенные).
Геометрия: эскиз участка строится кодом из зафиксированного blueprint; ручной эскиз мастера остаётся.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.core.layout import geometry, store
from app.core.layout.contracts import Blueprint, LayoutError
from app.core.layout.intent import LayoutIntent
from app.core.world_generation import storage
from app.core.world_generation.contracts import Blocked
from app.db.models import Entity, WorldGenerationState

log = logging.getLogger(__name__)

PHASES = ("location_layout", "location_geometry")


async def run(maker, dice_factory, claim: storage.Claim, phase: str, provider) -> dict[str, Any]:
    if phase == "location_layout":
        bp, quality = await _draft(maker, claim, provider)

        async def publish(ctx, row):
            return await _publish_layout(ctx, row, bp, quality)

        return await storage.commit_with(maker, dice_factory, claim, publish, quality=quality)
    return await storage.commit_with(maker, dice_factory, claim, _publish_geometry)


async def _draft(maker, claim: storage.Claim, provider) -> tuple[Blueprint, str]:
    async with maker() as s:
        row = await s.get(WorldGenerationState, claim.ref)
        res = dict(row.reservation or {})
    try:
        intent = LayoutIntent.model_validate(res["intent"])
    except (KeyError, ValidationError) as e:
        raise Blocked("unsupported_source", str(e)[:500]) from e
    kw = {"seed": int(res["seed"]), "root_id": res["root_id"], "plot_id": res.get("plot_id")}
    try:
        return provider.propose(intent, **kw), "normal"
    except LayoutError as e:
        first = e.errors
        log.info("структура %s: обычная раскладка не прошла (%s)", claim.ref, "; ".join(first[:3]))
    try:
        return provider.propose(intent, fallback=True, **kw), "fallback"
    except LayoutError as e:
        raise Blocked("layout_unsatisfiable", "; ".join((first + e.errors)[:6])) from e


async def _publish_layout(ctx, row: WorldGenerationState, bp: Blueprint, quality: str) -> dict[str, Any]:
    root = ctx.world.entities.get(row.target_entity_id)
    if root is None or root.kind != "location":
        raise Blocked("target_missing", "корневого места больше нет")
    if (root.state or {}).get("blueprint"):
        raise Blocked("target_missing", "у места уже есть blueprint")
    ids: dict[str, str] = {}
    for area in bp.areas:
        state: dict[str, Any] = {"complex": {"root_id": root.id, "area_ref": area.area_ref}}
        if area.secret:
            state["secret"] = True
        en = Entity(campaign_id=ctx.campaign.id, kind="location", name=area.public_name,
                    description=area.description, location_id=root.id, state=state)  # fmt: skip
        ctx.session.add(en)
        await ctx.session.flush()
        ctx.world.entities[en.id] = en
        ids[area.area_ref] = en.id
    passages = {p.passage_ref: {"state": p.state, "hidden": p.hidden} for p in bp.passages}
    root.state = {**(root.state or {}), "blueprint": bp.to_json(), "areas": ids, "passages": passages}
    rows_ = {}
    for area in bp.areas:
        g = await store.reserve_geometry(ctx.session, ctx.campaign.id, root, ctx.world.entities[ids[area.area_ref]], bp)
        rows_[area.area_ref] = g.id
    await ctx.record("prepare_layout", target_id=root.id, payload={"generation_id": row.id, "areas": len(ids)},
                     hidden=True)  # fmt: skip
    notes = [] if quality == "normal" else ["fallback:layout"]
    return {"schema_version": 1, "phase": "location_layout", "areas": ids, "geometry": rows_, "notes": notes}


async def _publish_geometry(ctx, row: WorldGenerationState) -> dict[str, Any]:
    res = dict(row.reservation or {})
    area = ctx.world.entities.get(row.target_entity_id)
    root = ctx.world.entities.get(res.get("root_id") or "")
    if area is None or root is None:
        raise Blocked("target_missing", "участка или комплекса больше нет")
    bp = store.blueprint_of(root)
    if bp is None or bp.revision != int(res.get("blueprint_rev") or 0):
        raise Blocked("stale_blueprint", "blueprint изменился после резерва")
    spec = bp.area(res.get("area_ref"))
    if spec is None:
        raise Blocked("target_missing", f"в blueprint нет участка {res.get('area_ref')}")
    current = (area.state or {}).get("sketch")
    if isinstance(current, dict) and current.get("cols") and not current.get("blueprint"):
        return {"schema_version": 1, "phase": "location_geometry", "area_ref": spec.area_ref,
                "notes": ["manual_preserved"]}  # fmt: skip
    try:
        sk = geometry.build_area(bp, spec, root_id=root.id, ids=store.area_ids(root))
    except geometry.GeometryError as e:
        raise Blocked("geometry_invalid", "; ".join(e.errors[:6])) from e
    edit_rev = int((current or {}).get("edit_rev") or 0) + 1
    area.state = {**(area.state or {}), "sketch": {**sk, "auto": True, "edit_rev": edit_rev}}
    await ctx.record("prepare_geometry", target_id=area.id,
                     payload={"generation_id": row.id, "area_ref": spec.area_ref}, hidden=True)  # fmt: skip
    return {"schema_version": 1, "phase": "location_geometry", "area_ref": spec.area_ref, "notes": []}
```

- [ ] **Step 5: Wire the executor into `Orchestrator`** (`app/core/world_generation/service.py`)

```python
    def __init__(self, coordination, bus=None, provider=None, dice_factory=Dice, llm=None, layout_provider=None):
        ...  # прежние присваивания
        from app.core.layout.provider import DeterministicLayoutProvider

        self.layout_provider = layout_provider or DeterministicLayoutProvider()

    async def prepare(self, maker, campaign_id: str, ref: str) -> str:
        """Довести фазу до ``ready``/``blocked``. Иначе вернуть, почему остановились. Обстановка участка комплекса
        сначала ждёт его геометрию: размещать её не на чем."""
        for dep in await _dependencies(maker, campaign_id, ref):
            await self.prepare(maker, campaign_id, dep)
        async with self.coordination.generation_lock(campaign_id):
            ...  # прежнее тело без изменений
```

В `_run` первые строки блока `try`:

```python
        from app.core.layout import executor

        try:
            phase = await storage.phase_of(maker, claim.ref)
            if phase in executor.PHASES:
                await executor.run(maker, self.dice_factory, claim, phase, self.layout_provider)
            else:
                draft = await self._plan(maker, claim)
                proposal, quality, claim = await self._propose(maker, claim, draft)
                await storage.commit_result(maker, self.dice_factory, claim, draft.plan, proposal, quality=quality)
        except Blocked as e:
            ...  # прежние ветки except без изменений
```

В конец модуля:

```python
async def _dependencies(maker, campaign_id: str, ref: str) -> list[str]:
    """Неготовые фазы, без которых эту не выполнить: обстановке участка комплекса нужна его геометрия."""
    async with maker() as s:
        row = await s.get(WorldGenerationState, ref)
        if row is None or row.campaign_id != campaign_id or row.phase != "location_initial":
            return []
        dep = await storage.find(s, campaign_id, row.target_entity_id, "location_geometry")
        if dep is None or dep.status in ("ready", "blocked"):
            return []
        if storage.activate(dep):
            await s.commit()
        return [dep.id]
```

- [ ] **Step 6: Add the host command `prepare_complex`** (`app/tools/master/generation.py`)

```python
HOST_TOOLS = frozenset({"resolve_location", "retry_preparation", "bind_plot_anchor", "prepare_complex"})


class PrepareComplexArgs(BaseModel):
    location_id: str = Field(description="реальный id места, которое станет комплексом участков")
    intent: LayoutIntent = Field(description="пространственный замысел: части, связи, подходы, дороги и ручьи")


@tool(
    "prepare_complex",
    "Команда ведущего: принимает пространственный замысел места и просит подготовить его структуру — участки и "
    "проходы между ними. Возвращает квитанцию; уже принятый замысел не перестраивается.",
    PrepareComplexArgs,
    ids={"location_id": "locations"},
    closes=False,
)
async def prepare_complex(ctx: ToolContext, a: PrepareComplexArgs) -> dict:
    from app.core import adventure
    from app.core.layout import store as layout_store

    w = ctx.world
    root = w.entities.get(a.location_id)
    if root is None or root.kind != "location" or root.campaign_id != ctx.campaign.id:
        raise ToolError("локация не принадлежит этой кампании")
    if layout_store.complex_of(root) is not None:
        raise ToolError("участок комплекса сам комплексом не становится")
    if adventure.room_of(root) is not None:
        raise ToolError("готовое приключение берёт план места из книги")
    for ap in a.intent.approaches:
        outside = w.entities.get(ap.outside_id or root.id)
        if outside is None or outside.kind != "location":
            raise ToolError(f"подход «{ap.public_name}»: нет места {ap.outside_id}")
    row = await storage.find(ctx.session, ctx.campaign.id, root.id, "location_layout")
    inverse: list = []
    if row is None:
        row = await layout_store.reserve_layout(ctx.session, ctx.campaign, root, a.intent)
        inverse.append({"table": "world_generation_states", "op": "delete", "id": row.id})
    elif (row.reservation or {}).get("intent") != a.intent.model_dump(mode="json"):
        raise ToolError("у места уже есть замысел комплекса: структура не перестраивается")
    storage.activate(row)
    result = {"location_id": root.id, **receipt(row.id)}
    await ctx.record("prepare_complex", target_id=root.id, payload=result, inverse=inverse, hidden=True)
    return result
```

Импорт вверху модуля: `from app.core.layout.intent import LayoutIntent`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout_preparation.py tests/test_world_generation.py tests/test_plot_anchors.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/core/layout/executor.py app/core/world_generation/storage.py app/core/world_generation/service.py app/tools/master/generation.py tests/test_layout_preparation.py
git commit -m "Структура и геометрия комплекса готовятся фазами с lease и CAS; ручной эскиз мастера остаётся

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Живое состояние прохода — одно на обе стороны

**Files:**
- Modify: `app/core/sketch.py` (`of_place`, `describe`)
- Modify: `app/tools/master/places.py` (`edit_sketch`, `sketch_place`)
- Modify: `app/agents/surveyor.py:84` (`draw`)
- Test: `tests/test_layout_passages.py`

**Interfaces:**
- Consumes: Task 6 `store.root_of`, `state.passages`; Task 7 подготовка.
- Produces: `sketch.of_place` накладывает `state`/`hidden` из `state.passages` корня на выходы с `passage_ref`;
  `edit_sketch` с `open|close|lock|unlock|reveal|hide` по выходу-проходу меняет только `state.passages` корня;
  остальные действия по нему и `sketch_place` поверх эскиза из blueprint — `ToolError`; `surveyor.draw` не строит
  эскиз участка, у которого эскиз из blueprint. `sketch.describe` показывает `проход <ref>`.

- [ ] **Step 1: Write the failing tests** — `tests/test_layout_passages.py`

```python
# ruff: noqa: F811
"""Проход комплекса общий для двух участков (спецификация 2026-10-12, §4): одно состояние, правка только корня."""

from types import SimpleNamespace

from app.agents import surveyor
from app.core import sketch
from app.db.models import Entity
from app.tools.registry import execute
from tests.game import run
from tests.test_layout_preparation import _activate, _areas, _complex, _setup
from tests.test_map import _ok, _play
from tests.test_world_generation import _fast_retry, _prepare, _with_maker  # noqa: F401 — фикстура


def _built(client, admin, settings, *names):
    """Комплекс подготовлен, у перечисленных участков готова геометрия."""
    cid, heads, hid = _setup(client, admin, settings)
    village, temple, ref = _complex(settings, cid)
    _prepare(settings, cid, ref)
    areas = _areas(settings, temple)
    for name in names:
        _prepare(settings, cid, _activate(settings, cid, areas[name].id))
    return cid, heads, hid, village, temple, {k: v.id for k, v in areas.items()}


def _exit(w, place, ref):
    sk = sketch.of_place(w.entities[place], w.catalog, w.entities)
    return next(x for x in sk["exits"] if x.get("passage_ref") == ref)


def test_door_state_is_shared_by_both_sides(client, admin, settings):
    cid, _h, _hid, _v, temple, ids = _built(client, admin, settings, "road", "narthex")

    async def go(ctx):
        w = ctx.world
        assert _exit(w, ids["road"], "p_narthex")["state"] == _exit(w, ids["narthex"], "p_narthex")["state"] == "closed"
        await _ok(ctx, "edit_sketch", {"action": "open", "target": "Двери храма", "location_id": ids["road"]})
        opened = (_exit(w, ids["road"], "p_narthex")["state"], _exit(w, ids["narthex"], "p_narthex")["state"])
        removed = await execute(ctx, "edit_sketch", {"action": "remove", "target": "Двери храма",
                                                     "location_id": ids["narthex"]})  # fmt: skip
        stored = w.entities[ids["road"]].state["sketch"]
        table = sketch.describe(sketch.of_place(w.entities[ids["road"]], w.catalog, w.entities))
        return opened, removed, stored, table

    opened, removed, stored, table = _play(settings, cid, go)
    assert opened == ("open", "open")
    assert not removed["ok"] and "общий для двух участков" in removed["error"]
    assert next(x for x in stored["exits"] if x["passage_ref"] == "p_narthex")["state"] == "closed"  # эскиз не правят
    assert "проход p_narthex" in table
    root = run(settings, lambda s: s.get(Entity, temple))
    assert root.state["passages"]["p_narthex"]["state"] == "open"


def test_secret_door_revealed_once_for_both_sides(client, admin, settings):
    cid, _h, _hid, _v, _t, ids = _built(client, admin, settings, "sacristy", "vault")

    async def go(ctx):
        w = ctx.world
        before = _exit(w, ids["vault"], "p_vault")["hidden"]
        await _ok(ctx, "edit_sketch", {"action": "reveal", "target": "Тайная дверь", "location_id": ids["sacristy"]})
        return before, _exit(w, ids["vault"], "p_vault")["hidden"]

    assert _play(settings, cid, go) == (True, False)


def test_surveyor_and_redraw_do_not_replace_blueprint_sketch(client, admin, settings):
    cid, _h, _hid, _v, _t, ids = _built(client, admin, settings, "road")

    async def describe(ctx):
        layout = "Поле у дороги, сорок футов в каждую сторону, на севере стена храма, двери закрыты."
        await _ok(ctx, "describe_place", {"layout": layout, "location_id": ids["road"]})
        redraw = await execute(ctx, "sketch_place", {"shape": "open", "cols": 4, "rows": 4, "party": [0, 0],
                                                     "location_id": ids["road"]})  # fmt: skip
        return redraw

    redraw = _play(settings, cid, describe)
    assert not redraw["ok"] and "участок комплекса" in redraw["error"]
    drawn = _with_maker(settings, lambda maker: surveyor.draw(SimpleNamespace(maker=maker), cid, ids["road"]))
    assert drawn is None
    road = run(settings, lambda s: s.get(Entity, ids["road"]))
    assert road.state["sketch"]["blueprint"]["area_ref"] == "road"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout_passages.py -q`
Expected: FAIL — состояние двери с другой стороны остаётся `closed`.

- [ ] **Step 3: Overlay live passages in `app/core/sketch.py`**

```python
def _live_passages(sk: dict, entities: dict) -> dict:
    """Проход комплекса общий для двух участков: открыт ли он и тайный ли — из ``state.passages`` корня."""
    root = entities.get((sk.get("blueprint") or {}).get("root_id") or "")
    live = ((root.state or {}).get("passages") or {}) if root is not None else {}
    if not live:
        return sk
    exits = []
    for x in sk.get("exits") or []:
        now = live.get(x.get("passage_ref") or "") or {}
        exits.append({**x, **{k: now[k] for k in ("state", "hidden") if k in now}})
    return {**sk, "exits": exits}
```

В `of_place`:

```python
    sk = (e.state or {}).get("sketch")
    if isinstance(sk, dict) and sk.get("cols"):
        return _live_passages(sk, entities) if sk.get("blueprint") else sk
```

В `describe`, в сборке строки выхода, перед `+ (", тайный" ...)`:

```python
        + (f", проход {x['passage_ref']}" if x.get("passage_ref") else "")
```

- [ ] **Step 4: Route passage edits to the root in `app/tools/master/places.py`**

Перед `edit_sketch`:

```python
PASSAGE_ACTIONS = {
    "open": ("state", "open"),
    "close": ("state", "closed"),
    "lock": ("state", "locked"),
    "unlock": ("state", "closed"),
    "reveal": ("hidden", False),
    "hide": ("hidden", True),
}


def _passage_exit(current: dict, a: EditSketchArgs) -> dict | None:
    """Выход-проход комплекса, к которому обращается правка."""
    if not a.target or a.action in ("add_feature", "add_exit"):
        return None
    want = a.target.strip().lower()
    return next(
        (
            x
            for x in current.get("exits") or []
            if x.get("passage_ref") and (x["name"].strip().lower() == want or x["passage_ref"] == a.target)
        ),
        None,
    )


async def _edit_passage(ctx: ToolContext, place: Entity, x: dict, a: EditSketchArgs) -> dict:
    """Состояние прохода общее для обоих участков: меняется только у корня, эскизы сторон не трогаются."""
    from app.core.layout import store

    if a.action not in PASSAGE_ACTIONS or a.rename:
        raise ToolError(
            f"«{x['name']}» — проход комплекса, общий для двух участков: для него open, close, lock, unlock, reveal "
            "или hide"
        )
    root = store.root_of(ctx.world.entities, place)
    if root is None:
        raise ToolError("комплекс этого участка не найден")
    key, value = PASSAGE_ACTIONS[a.action]
    before = copy.deepcopy(root.state)
    passages = dict((root.state or {}).get("passages") or {})
    passages[x["passage_ref"]] = {**(passages.get(x["passage_ref"]) or {}), key: value}
    root.state = {**(root.state or {}), "passages": passages}
    ctx.signals.add("map.changed")
    await ctx.record(
        "edit_sketch",
        target_id=place.id,
        payload={"place": place.name, "action": a.action, "target": x["name"], "passage_ref": x["passage_ref"]},
        inverse=[{"table": "entities", "id": root.id, "field": "state", "before": before}],
    )
    return {"place": place.name, "passage": x["name"], key: value}
```

В `edit_sketch` сразу после `revision = _verify_sketch_revision(...)`:

```python
    passage = _passage_exit(current, a)
    if passage is not None:
        return await _edit_passage(ctx, place, passage, a)
```

В `sketch_place` — до записи нового эскиза, рядом с проверкой ревизии текущего:

```python
    if ((place.state or {}).get("sketch") or {}).get("blueprint"):
        raise ToolError("участок комплекса: его форма общая с соседями — правь edit_sketch, а не перерисовывай")
```

(точное место: после того как `place` найден и заблокирован `_lock_sketch_place`.)

- [ ] **Step 5: Guard the surveyor** (`app/agents/surveyor.py`, первая проверка в `draw`)

```python
        if c is None or place is None or not st.get("layout") or (st.get("sketch") or {}).get("blueprint"):
            return None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout_passages.py tests/test_sketch.py tests/test_surveyor.py tests/test_world_objects_sketch.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/core/sketch.py app/tools/master/places.py app/agents/surveyor.py tests/test_layout_passages.py
git commit -m "Дверь комплекса открывается сразу с обеих сторон; эскиз участка не перерисовывают поверх blueprint

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Соседство участков и зацепки каркаса

**Files:**
- Modify: `app/core/topology.py` (`location_exits`)
- Modify: `app/core/plot_anchors.py:114-120` (`reserved_for`)
- Modify: `app/core/world_generation/storage.py:340-350` (проверка привязки в `commit_result`)
- Modify: `app/core/layout/executor.py` (`_draft`: незакреплённые зацепки корня — во входной участок)
- Test: `tests/test_layout_topology.py`

**Interfaces:**
- Consumes: Task 6 store; Task 7 executor.
- Produces: `location_exits(area)` — соседи по проходам blueprint (без тайных), метка — публичное имя прохода, без
  «наружу» к корню; у корня с blueprint участки не числятся «внутри»; внешнее место видит участки за подходами.
  `reserved_for(session, cid, location_id)` — для участка ещё и зацепки корня, отданные ему blueprint; для корня с
  blueprint — без них.

- [ ] **Step 1: Write the failing tests** — `tests/test_layout_topology.py`

```python
# ruff: noqa: F811
"""Соседство участков и зацепки каркаса (спецификация 2026-10-12, §3.1, §4)."""

from sqlalchemy import select

from app.core import plot_anchors
from app.core.layout import store
from app.core.topology import location_exits
from app.db.models import Entity, PlotAnchorBinding
from tests.game import run
from tests.test_layout_passages import _built
from tests.test_layout_preparation import _areas, _complex, _setup
from tests.test_map import _map, _ok, _play
from tests.test_world_generation import _fast_retry, _prepare  # noqa: F401 — фикстура


def _entities(settings):
    async def go(s):
        return {e.id: e for e in (await s.scalars(select(Entity))).all()}

    return run(settings, go)


def test_area_neighbours_follow_passages_not_nesting(client, admin, settings):
    cid, _h, _hid, village, temple, ids = _built(client, admin, settings)
    ents = _entities(settings)
    road = {x.target_id: x.label for x in location_exits(ents[ids["road"]], None, ents)}
    assert road == {ids["brook"]: "Луг", ids["narthex"]: "Двери храма", village: "Дорога в деревню"}
    assert ids["vault"] not in {x.target_id for x in location_exits(ents[ids["sacristy"]], None, ents)}
    assert not {x.target_id for x in location_exits(ents[temple], None, ents)} & set(ids.values())
    assert ids["road"] in {x.target_id for x in location_exits(ents[village], None, ents)}


def test_player_map_hides_secret_passage_and_area(client, admin, settings):
    cid, heads, hid, _v, _t, ids = _built(client, admin, settings, "sacristy")

    async def go(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["sacristy"]})

    _play(settings, cid, go)
    m = _map(client, heads[0], cid)
    assert ids["vault"] not in str(m) and "p_vault" not in str(m) and "Тайная дверь" not in str(m)


def test_root_anchor_follows_its_area(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)

    async def bind(ctx):
        village = (await _ok(ctx, "create_location", {"name": "Деревня", "make_current": True}))["location_id"]
        temple = (await _ok(ctx, "create_location", {"name": "Старый храм"}))["location_id"]
        for anchor in ("relic", "note"):
            ctx.session.add(PlotAnchorBinding(campaign_id=cid, anchor_id=anchor, plot_ref="r1",
                                              target_location_id=temple, state="reserved",
                                              source_snapshot={"carrier": {"name": anchor}}))  # fmt: skip
        return village, temple

    village, temple = _play(settings, cid, bind)
    from tests.layout_pilot import pilot_intent

    async def plan(ctx):
        intent = pilot_intent(village).model_dump(mode="json")
        return (await _ok(ctx, "prepare_complex", {"location_id": temple, "intent": intent}))["operation_ref"]

    _prepare(settings, cid, _play(settings, cid, plan))
    areas = {k: v.id for k, v in _areas(settings, temple).items()}
    root = _entities(settings)[temple]
    assert store.blueprint_of(root).anchors == {"relic": "chapel", "note": "road"}

    async def check(s):
        here = {a: [b.anchor_id for b in await plot_anchors.reserved_for(s, cid, x)] for a, x in areas.items()}
        return here, [b.anchor_id for b in await plot_anchors.reserved_for(s, cid, temple)]

    here, at_root = run(settings, check)
    assert here["chapel"] == ["relic"] and here["road"] == ["note"] and here["nave"] == [] and at_root == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout_topology.py -q`
Expected: FAIL — у дороги соседи по вложенности («наружу» к храму) вместо проходов.

- [ ] **Step 3: Passages as neighbours in `app/core/topology.py`**

После ветки книги (`if ref is not None: ...`) и проверки `place.kind != "location"`:

```python
    from app.core.layout import store

    cx = store.complex_of(place)
    if cx is not None:
        return _passage_exits(place, entities.get(cx["root_id"]), entities)
```

В цикле «внутри» пропускать участки: `if other.kind == "location" and other.location_id == place.id and not
store.complex_of(other):`. Перед `add(place.location_id, "наружу")` добавить подходы снаружи:

```python
    for root in entities.values():
        bp = store.blueprint_of(root) if root.kind == "location" else None
        if bp is None:
            continue
        ids = store.area_ids(root)
        for p in bp.passages:
            if store.passage_live(root, p.passage_ref).get("hidden", p.hidden):
                continue
            for i, x in enumerate(p.ends):
                if x.external and x.place_id == place.id:
                    add(ids.get(p.ends[1 - i].area_ref or ""), p.public_name)
```

И функция в модуле:

```python
def _passage_exits(place: Entity, root: Entity | None, entities: dict[str, Entity]) -> list[LocationExit]:
    """Соседи участка комплекса — только через его проходы; тайный проход соседства не даёт, пока его не нашли.
    Вложенность в корень прохода не создаёт."""
    from app.core.layout import store

    bp = store.blueprint_of(root)
    if bp is None:
        return []
    ids = store.area_ids(root)
    area_ref = store.complex_of(place)["area_ref"]
    out: list[LocationExit] = []
    for p, x in bp.ends_of(area_ref):
        if store.passage_live(root, p.passage_ref).get("hidden", p.hidden):
            continue
        o = bp.other(p, x)
        target = ids.get(o.area_ref) if o.area_ref else o.place_id
        if target and target in entities and target not in {e.target_id for e in out}:
            out.append(LocationExit(target, None, p.public_name, x.side))
    return out
```

- [ ] **Step 4: Complex-aware `reserved_for`** (`app/core/plot_anchors.py`; добавить `Entity` к импорту моделей, если его нет)

```python
async def reserved_for(session: AsyncSession, campaign_id: str, location_id: str) -> list[PlotAnchorBinding]:
    """Зацепки, которые ждут места. Участок комплекса получает и зацепки корня, отданные ему blueprint; корень с
    blueprint их уже не держит (спецификация 2026-10-12, §3.1)."""
    from app.core.layout import store

    base = _of(campaign_id).where(
        PlotAnchorBinding.state == "reserved", PlotAnchorBinding.holder_entity_id.is_(None)
    )
    place = await session.get(Entity, location_id)
    cx = store.complex_of(place)
    if cx is not None:
        bp = store.blueprint_of(await session.get(Entity, cx["root_id"]))
        mine = {a for a, ref in (bp.anchors if bp else {}).items() if ref == cx["area_ref"]}
        q = base.where(PlotAnchorBinding.target_location_id.in_((location_id, cx["root_id"])))
        return [b for b in await session.scalars(q) if b.target_location_id == location_id or b.anchor_id in mine]
    found = list(await session.scalars(base.where(PlotAnchorBinding.target_location_id == location_id)))
    bp = store.blueprint_of(place)
    return [b for b in found if b.anchor_id not in bp.anchors] if bp is not None else found
```

В `storage.commit_result` перед циклом по слотам: `here = {b.anchor_id for b in await plot_anchors.reserved_for(s,
campaign.id, place)}`, а условие пропуска привязки заменить на
`if b is None or b.state != "reserved" or b.holder_entity_id or b.anchor_id not in here:`.

- [ ] **Step 5: Unmapped root anchors go to the entry area** (`app/core/layout/executor.py`, `_draft`)

Внутри `async with maker() as s:` после чтения `res`:

```python
        from app.core import plot_anchors

        waiting = [b.anchor_id for b in await plot_anchors.reserved_for(s, claim.campaign_id, row.target_entity_id)]
```

и вместо двух `return provider.propose(...)` — общий хвост:

```python
def _with_anchors(bp: Blueprint, waiting: list[str]) -> Blueprint:
    """Зацепка корня без места в замысле не теряется: её получает входной участок."""
    extra = {a: bp.entry for a in waiting if a not in bp.anchors}
    return replace(bp, anchors={**bp.anchors, **extra}) if extra else bp
```

(`from dataclasses import replace`), т. е. `return _with_anchors(provider.propose(intent, **kw), waiting), "normal"`
и то же для fallback.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout_topology.py tests/test_topology.py tests/test_plot_anchors.py tests/test_map.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/core/topology.py app/core/plot_anchors.py app/core/world_generation/storage.py app/core/layout/executor.py tests/test_layout_topology.py
git commit -m "Участки соседствуют по проходам, зацепки каркаса следуют за своим участком

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Обстановка на геометрии участка

**Files:**
- Create: `app/core/layout/furnish.py`
- Modify: `app/core/world_generation/storage.py` (`commit_result`: сбор `placed` и вызов `_furnish`)
- Test: `tests/test_layout_furnish.py`

**Interfaces:**
- Consumes: Task 1 `sketch.floor_cells/exit_cells`, `reach.blocked_cells/reach_errors`; Task 7 подготовка.
- Produces: `furnish.place(sk: dict, objects: list[tuple[str, str]], seed: int) -> tuple[dict, list[str]]` —
  новый эскиз со связанными деталями 1×1 (`id=f"sf_{entity_id}"`, `entity_id`, `kind="object"`) и id не
  поместившихся. Подготовка обстановки участка комплекса пишет их в эскиз и `notes: ["unplaced:<id>"]`.

- [ ] **Step 1: Write the failing tests** — `tests/test_layout_furnish.py`

```python
# ruff: noqa: F811
"""Обстановка участка на его геометрии (спецификация 2026-10-12, §3.4): связанные детали, проходы свободны."""

from app.core import positions as grid
from app.core import reach, sketch
from app.core.layout import furnish
from app.db.models import Entity, WorldGenerationState
from tests.game import run
from tests.test_layout_passages import _built
from tests.test_map import _ok, _play
from tests.test_world_generation import _fast_retry, _generated, _prepare, _row  # noqa: F401 — фикстура

FIELD = {"shape": "room", "cols": 6, "rows": 5, "party": [0, 2], "walls": [], "features": [],
         "exits": [{"name": "Ворота", "side": "w", "at": 2, "kind": "gate", "state": "open", "cells": [[0, 2]]},
                   {"name": "Дверь", "side": "e", "at": 2, "kind": "door", "state": "open", "cells": [[5, 2]]}]}  # fmt: skip


def test_place_keeps_passages_free_and_is_deterministic():
    objects = [("en_a", "Сундук"), ("en_b", "Бочка"), ("en_c", "Скамья")]
    sk, unplaced = furnish.place(FIELD, objects, seed=3)
    assert unplaced == [] and sk == furnish.place(FIELD, objects, seed=3)[0]
    linked = [f for f in sk["features"] if f.get("entity_id")]
    assert [f["entity_id"] for f in linked] == ["en_a", "en_b", "en_c"]
    near_exits = {(c + dc, r + dr) for x in FIELD["exits"] for c, r in sketch.exit_cells(FIELD, x)
                  for dc in (-1, 0, 1) for dr in (-1, 0, 1)}  # fmt: skip
    assert not any(tuple(f["cells"][0][:2]) in near_exits for f in linked)
    assert reach.reach_errors(sk) == [] and sketch.check(sk, set()) == []


def test_crowded_area_leaves_objects_unplaced():
    tiny = {**FIELD, "cols": 3, "rows": 1, "party": [0, 0], "exits": []}
    sk, unplaced = furnish.place(tiny, [("en_a", "Сундук"), ("en_b", "Бочка")], seed=1)
    assert len(unplaced) >= 1 and len([f for f in sk["features"] if f.get("entity_id")]) + len(unplaced) == 2


def test_generated_furnishing_is_bound_to_area_cells(client, admin, settings):
    cid, _h, _hid, _v, _t, ids = _built(client, admin, settings)

    async def resolve(ctx):
        ctx.campaign.settings = {**(ctx.campaign.settings or {}), "scene_generation": True}
        out = await _ok(ctx, "resolve_location", {"location_id": ids["chapel"], "profile_id": "scene_profile.warehouse"})
        return out["operation_ref"]

    ref = _play(settings, cid, resolve)
    assert _prepare(settings, cid, ref) == "ready"
    made = [e for e in _generated(settings, ref) if (e.state or {}).get("world_object", {}).get("role") != "item"]
    chapel = run(settings, lambda s: s.get(Entity, ids["chapel"]))
    linked = {f["entity_id"] for f in chapel.state["sketch"]["features"] if f.get("entity_id")}
    notes = _row(settings, ref).result_manifest["notes"]
    assert made and {e.id for e in made} == linked | {n.split(":", 1)[1] for n in notes if n.startswith("unplaced:")}
    assert reach.reach_errors(chapel.state["sketch"]) == []

    moved = sorted(linked)[0]

    async def carry(ctx):
        ctx.world.entities[moved].location_id = ids["nave"]
        return [f.get("entity_id") for f in (grid._sketch(ctx.world, ids["chapel"]) or {}).get("features") or []]

    assert moved not in _play(settings, cid, carry)  # перенесённый объект не оставляет блокирующий рисунок
    assert WorldGenerationState.__tablename__
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout_furnish.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.layout.furnish'`.

- [ ] **Step 3: Implement `app/core/layout/furnish.py`**

```python
"""Обстановка участка на его геометрии (спецификация 2026-10-12, §3.4): интерактивный объект — сущность мира, на
эскизе он — связанная деталь в одну клетку, второго объекта рисунок не создаёт. Клетки у проходов и точка входа
участка свободны; каждая расстановка проверяется досягаемостью (app/core/reach.py), поэтому объект не отрезает
выходы и к нему можно подойти. Не поместившийся объект остаётся в мире без клетки — диагностика в manifest.
"""

from __future__ import annotations

import copy
import random

from app.core import reach, sketch


def place(sk: dict, objects: list[tuple[str, str]], seed: int) -> tuple[dict, list[str]]:
    floor = sketch.floor_cells(sk) or {(c, r) for c in range(sk["cols"]) for r in range(sk["rows"])}
    keep = {tuple(sk["party"])}
    for x in sk.get("exits") or []:
        for c, r in sketch.exit_cells(sk, x):
            keep |= {(c + dc, r + dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1)}
    free = sorted(c for c in floor if c not in reach.blocked_cells(sk) and c not in keep)
    random.Random(seed).shuffle(free)
    out = copy.deepcopy(sk)
    features = list(out.get("features") or [])
    unplaced: list[str] = []
    for entity_id, name in objects:
        for i, (c, r) in enumerate(free):
            feature = {"id": f"sf_{entity_id}"[:32], "entity_id": entity_id, "name": name, "kind": "object",
                       "cells": [[c, r, c, r]], "cover": "none", "hidden": False}  # fmt: skip
            trial = {**out, "features": [*features, feature]}
            if not reach.reach_errors(trial):
                features.append(feature)
                free.pop(i)
                break
        else:
            unplaced.append(entity_id)
    out["features"] = features
    return out, unplaced
```

- [ ] **Step 4: Furnish in `commit_result`** (`app/core/world_generation/storage.py`)

Рядом с `made: dict[str, str] = {}` добавить `placed: list[tuple[str, str]] = []`; после
`made[slot.slot_ref] = en.id`:

```python
            if slot.role != "item" and slot.anchor_id is None:
                placed.append((en.id, en.name))
```

Перед сборкой `manifest`:

```python
        if root:
            notes += _furnish(target, placed, int(row.seed or 0))
```

И функция модуля:

```python
def _furnish(place: Entity, placed: list[tuple[str, str]], seed: int) -> list[str]:
    """Обстановка участка комплекса встаёт на его геометрию связанными деталями (спецификация 2026-10-12, §3.4)."""
    from app.core.layout import furnish

    sk = (place.state or {}).get("sketch")
    if not placed or not isinstance(sk, dict) or not sk.get("blueprint"):
        return []
    new, unplaced = furnish.place(sk, placed, seed)
    place.state = {**(place.state or {}), "sketch": {**new, "edit_rev": int(sk.get("edit_rev") or 0) + 1}}
    return [f"unplaced:{x}" for x in unplaced]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout_furnish.py tests/test_world_generation.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/core/layout/furnish.py app/core/world_generation/storage.py tests/test_layout_furnish.py
git commit -m "Обстановка участка комплекса встаёт на его клетки, не загораживая проходы

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Переход через проход и событие игрока `map.traverse`

**Files:**
- Create: `app/core/layout/transit.py`
- Modify: `app/gateway/ws.py` (диспетчер, `_traverse`, docstring), `app/gateway/protocol.py` (`MapTraverseResult`)
- Test: `tests/test_layout_transit.py`

**Interfaces:**
- Consumes: Task 6 store (`request_geometry`); Task 7 подготовка; Task 8 `of_place` с живыми проходами;
  `places.request_preparation`, `places.move_heroes`; `steps.search/cell_of`; `positions.to_master/to_rel/
  free_cells_near/set_cell`.
- Produces: `Request{hero_ids, passage_ref, root_id, source_id, dest_id, blueprint_rev, refs, lane}` с `to_json/from_json`;
  `async begin(ctx, hero_ids, passage_ref, inverse) -> Request`; `async finish(ctx, req, inverse=None) -> dict`
  (`{moved: True, area_id, area, passage, from_cell, cell, event_id, ...}` или `{moved: False, reason}`);
  `async traverse(maker, preparer, dice_factory, campaign_id, hero_id, passage_ref) -> tuple[dict, ctx | None, list]`.
  Событие WS: вход `map.traverse {passage_ref, request_id, as_seat?}` → `map.traverse.result {request_id, ok, ...}`.
  События журнала: `request_passage` (скрытое, подготовка принята), `traverse_passage` (переход).

- [ ] **Step 1: Write the failing tests** — `tests/test_layout_transit.py`

```python
# ruff: noqa: F811
"""Переход между участками (спецификация 2026-10-12, §5, §7, §8): сначала подготовка, потом проверка и шаг."""

from app.core import steps
from app.core import positions as grid
from app.core.layout import transit
from app.core.world_generation import storage
from app.db.models import Character, Event
from tests.game import run
from tests.test_layout_passages import _built
from tests.test_map import _ok, _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry, _prepare  # noqa: F401 — фикстура
from tests.test_ws import connect, next_of


def _go(client, head, cid, ref):
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "map.traverse", "payload": {"passage_ref": ref, "request_id": "r1"}})
        return next_of(ws, "map.traverse.result")["payload"]


def _place(settings, hid):
    return run(settings, lambda s: s.get(Character, hid)).location_id


def test_traverse_from_outside_prepares_then_moves(client, admin, settings):
    cid, heads, hid, village, _t, ids = _built(client, admin, settings)
    out = _go(client, heads[0], cid, "in_road_w")
    assert out["ok"] and out["moved"] and out["area_id"] == ids["road"]
    assert _place(settings, hid) == ids["road"] and out["cell"] in ([0, 3], [0, 4])
    geometry = run(settings, lambda s: storage.find(s, cid, ids["road"], "location_geometry"))
    assert geometry.status == "ready"
    assert len(rows(settings, Event, Event.tool == "traverse_passage")) == 1


def test_open_field_keeps_the_lane_both_ways(client, admin, settings):
    cid, heads, hid, _v, _t, ids = _built(client, admin, settings)
    _go(client, heads[0], cid, "in_road_w")
    east = _go(client, heads[0], cid, "p_brook")
    assert east["moved"] and east["cell"][0] == 0 and east["cell"][1] == east["from_cell"][1]
    west = _go(client, heads[0], cid, "p_brook")
    assert west["moved"] and west["cell"][0] == 11 and west["cell"][1] == west["from_cell"][1]
    assert _place(settings, hid) == ids["road"]


def test_closed_door_refuses(client, admin, settings):
    cid, heads, _hid, _v, _t, _ids = _built(client, admin, settings)
    _go(client, heads[0], cid, "in_road_w")
    out = _go(client, heads[0], cid, "p_narthex")
    assert not out["ok"] and "закрыт" in out["error"]


def test_hidden_passage_reads_as_missing(client, admin, settings):
    cid, heads, hid, _v, _t, ids = _built(client, admin, settings, "sacristy")

    async def go(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["sacristy"]})

    _play(settings, cid, go)
    secret, missing = _go(client, heads[0], cid, "p_vault"), _go(client, heads[0], cid, "p_nowhere")
    assert not secret["ok"] and secret["error"] == missing["error"] == "отсюда нет такого прохода"


def test_door_closed_during_preparation_keeps_area_but_not_hero(client, admin, settings):
    cid, heads, hid, _v, _t, ids = _built(client, admin, settings)
    _go(client, heads[0], cid, "in_road_w")

    async def begin(ctx):
        await _ok(ctx, "edit_sketch", {"action": "open", "target": "Двери храма", "location_id": ids["road"]})
        req = await transit.begin(ctx, [hid], "p_narthex", [])
        return req.to_json()

    req = _play(settings, cid, begin)
    assert req["refs"]

    async def close(ctx):
        await _ok(ctx, "edit_sketch", {"action": "close", "target": "Двери храма", "location_id": ids["road"]})

    _play(settings, cid, close)
    for ref in req["refs"]:
        _prepare(settings, cid, ref)

    async def finish(ctx):
        return await transit.finish(ctx, transit.Request.from_json(req))

    out = _play(settings, cid, finish)
    assert not out["moved"] and "закрыт" in out["reason"]
    assert _place(settings, hid) == ids["road"]
    geometry = run(settings, lambda s: storage.find(s, cid, ids["narthex"], "location_geometry"))
    assert geometry.status == "ready"


def test_walking_to_the_door_happens_before_preparation(client, admin, settings):
    cid, heads, hid, _v, _t, ids = _built(client, admin, settings)
    _go(client, heads[0], cid, "in_road_w")

    async def go(ctx):
        await _ok(ctx, "edit_sketch", {"action": "open", "target": "Двери храма", "location_id": ids["road"]})
        await transit.begin(ctx, [hid], "p_narthex", [])
        w = ctx.world
        return grid.to_master(w, ids["road"], steps.cell_of(w, hid)), w.actor_place(hid)

    cell, place = _play(settings, cid, go)
    assert cell == (6, 0) and place == ids["road"]  # у дверей, но ещё не внутри
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout_transit.py -q`
Expected: FAIL — `неизвестное событие 'map.traverse'` / `ModuleNotFoundError ... transit`.

- [ ] **Step 3: Implement `app/core/layout/transit.py`**

```python
"""Переход между участками комплекса (спецификация 2026-10-12, §5, §7, §8).

``begin`` в транзакции команды проверяет героев и проход, подводит первого героя к проходу (вне боя) и запрашивает
подготовку участка назначения, не меняя места героев. ``finish`` в отдельной транзакции после подготовки заново
проверяет место героев, их клетку у прохода, состояние прохода и ревизию blueprint и только тогда переводит героев;
иначе готовый участок остаётся, а перехода нет. На широком свободном крае герой выходит на той же «полосе», где
перешёл. Переход ведёт сервер: клиент не перемещает героя из-за панорамирования карты.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any

from app.core import combat, sketch, steps
from app.core import positions as grid
from app.core.layout import store
from app.core.layout.contracts import Blueprint, End, Passage
from app.db.models import Campaign, Entity
from app.tools.registry import ToolError

QUEUE = "transits"
STATE_NAMES = {"closed": "закрыт", "locked": "заперт"}
MISSING = "отсюда нет такого прохода"


@dataclass(frozen=True)
class Request:
    hero_ids: tuple[str, ...]
    passage_ref: str
    root_id: str
    source_id: str
    dest_id: str
    blueprint_rev: int
    refs: tuple[str, ...]
    lane: int = 0

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "hero_ids": list(self.hero_ids), "refs": list(self.refs)}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Request:
        return cls(tuple(d["hero_ids"]), d["passage_ref"], d["root_id"], d["source_id"], d["dest_id"],
                   int(d["blueprint_rev"]), tuple(d.get("refs") or ()), int(d.get("lane") or 0))  # fmt: skip


def find_passage(world, place_id: str | None, passage_ref: str) -> tuple[Entity, Blueprint, Passage, End, End]:
    """Корень, blueprint, проход, конец со стороны ``place_id`` и противоположный конец."""
    place = world.entities.get(place_id or "")
    root = store.root_of(world.entities, place)
    roots = [root] if root is not None else [
        e for e in world.entities.values() if e.kind == "location" and (e.state or {}).get("blueprint")
    ]  # fmt: skip
    for r in roots:
        bp = store.blueprint_of(r)
        p = bp.passage(passage_ref) if bp is not None else None
        if p is None:
            continue
        ids = store.area_ids(r)
        for i, end in enumerate(p.ends):
            here = ids.get(end.area_ref) if end.area_ref else end.place_id
            if here == place_id:
                return r, bp, p, end, p.ends[1 - i]
    raise ToolError(MISSING)


def _live(root: Entity, p: Passage) -> dict:
    return {"state": p.state, "hidden": p.hidden, **store.passage_live(root, p.passage_ref)}


def check(world, hero_ids: list[str], passage_ref: str) -> tuple[str, Entity, Blueprint, Passage, End, End]:
    places = {world.actor_place(h) for h in hero_ids}
    if len(places) != 1:
        raise ToolError("проходят вместе только герои из одного места")
    here = places.pop()
    root, bp, p, end, other = find_passage(world, here, passage_ref)
    live = _live(root, p)
    if live["hidden"]:
        raise ToolError(MISSING)  # тайный проход отвечает как несуществующий
    if live["state"] != "open":
        raise ToolError(f"«{p.public_name}» {STATE_NAMES.get(live['state'], live['state'])}: сначала откройте")
    return here, root, bp, p, end, other


def endpoint_cells(world, area_id: str, passage_ref: str) -> list[tuple[int, int]] | None:
    """Клетки у прохода в координатах мастера по текущему эскизу; None — эскиз без этого прохода (ручной)."""
    sk = grid._sketch(world, area_id)
    x = next((x for x in (sk or {}).get("exits") or [] if x.get("passage_ref") == passage_ref), None)
    return sketch.exit_cells(sk, x) if x is not None else None


def _approach(ctx, hero_id: str, here: str, end: End, p: Passage, inverse: list) -> int:
    """Подвести героя к проходу вне боя; вернуть индекс клетки прохода, где он стоит."""
    w = ctx.world
    if end.external:
        return 0  # снаружи комплекса: достаточно быть в этом месте
    cells = endpoint_cells(w, here, p.passage_ref)
    if not cells:
        return 0
    me = grid.to_master(w, here, steps.cell_of(w, hero_id))
    if me in cells:
        return cells.index(me)
    if combat.in_combat(ctx) and combat.fights(w.scene, w.characters, w.entities, hero_id):
        raise ToolError(f"в бою к «{p.public_name}» подходят своим ходом: встаньте у прохода")
    goal = {grid.to_rel(w, here, c) for c in cells}
    route = steps.search(w, here, steps.cell_of(w, hero_id), lambda c: c in goal, hero_id)
    if route is None:
        raise ToolError(f"к «{p.public_name}» не подойти: путь закрыт")
    if route:
        inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "state",
                        "before": copy.deepcopy(w.scene.state)})  # fmt: skip
        grid.set_cell(w, hero_id, route[-1])
        ctx.changed.add(hero_id)
    return cells.index(grid.to_master(w, here, route[-1] if route else steps.cell_of(w, hero_id)))


async def request_area(ctx, area: Entity, inverse: list) -> list[str]:
    """Подготовка участка до входа: геометрия и обстановка. Возвращает ref ещё не готовых фаз."""
    from app.core.world_generation import storage
    from app.tools.master.places import request_preparation

    refs = []
    geo = await store.request_geometry(ctx, area)
    if geo:
        refs.append(geo)
    await request_preparation(ctx, area, inverse)
    row = await storage.find(ctx.session, ctx.campaign.id, area.id, "location_initial")
    if row is not None and row.status in ("unprepared", "preparing") and row.requested_at is not None:
        refs.append(row.id)
    return refs


async def begin(ctx, hero_ids: list[str], passage_ref: str, inverse: list) -> Request:
    w = ctx.world
    for h in hero_ids:
        hero = w.actor(h)
        if not hero.alive or hero.hp.current <= 0:
            raise ToolError(f"{hero.name} без сознания и не может идти")
    here, root, bp, p, end, other = check(w, hero_ids, passage_ref)
    lane = _approach(ctx, hero_ids[0], here, end, p, inverse)
    dest_id = store.area_ids(root).get(other.area_ref) if other.area_ref else other.place_id
    dest = w.entities.get(dest_id or "")
    if dest is None:
        raise ToolError(f"за «{p.public_name}» пока ничего нет")
    refs = await request_area(ctx, dest, inverse)
    return Request(tuple(hero_ids), passage_ref, root.id, here, dest.id, bp.revision, tuple(refs), lane)


async def _geometry_ready(ctx, dest: Entity) -> str | None:
    """Почему в участок ещё нельзя войти; None — можно."""
    from app.core.world_generation import storage

    if store.complex_of(dest) is None:
        return None
    row = await storage.find(ctx.session, ctx.campaign.id, dest.id, "location_geometry")
    if row is not None and row.status == "ready":
        return None
    return row.last_error if row is not None and row.status == "blocked" else "участок ещё готовится"


async def finish(ctx, req: Request, inverse: list | None = None) -> dict[str, Any]:
    from app.tools.master.places import move_heroes

    w = ctx.world
    try:
        here, root, bp, p, end, other = check(w, list(req.hero_ids), req.passage_ref)
    except ToolError as e:
        return {"moved": False, "reason": str(e)}
    if here != req.source_id or root.id != req.root_id or bp.revision != req.blueprint_rev:
        return {"moved": False, "reason": "герои уже не у этого прохода"}
    first = req.hero_ids[0]
    before = grid.to_master(w, here, steps.cell_of(w, first))
    cells = endpoint_cells(w, here, p.passage_ref) if not end.external else None
    if cells and before not in cells:
        return {"moved": False, "reason": f"герой отошёл от «{p.public_name}»"}
    dest = w.entities.get(req.dest_id)
    problem = "участка за проходом нет" if dest is None else await _geometry_ready(ctx, dest)
    if problem:
        return {"moved": False, "reason": f"за «{p.public_name}» пока не пройти: {problem}"}
    inverse = list(inverse or [])
    dice: list = []
    heroes = [w.characters[h] for h in req.hero_ids]
    joined = await move_heroes(ctx, heroes, dest, inverse, dice)
    cell = _arrive(ctx, heroes, dest, p, other, req.lane, inverse)
    out = {"moved": True, "area_id": dest.id, "area": dest.name, "passage": p.public_name,
           "from_cell": list(before), "cell": list(cell) if cell else None, **joined}  # fmt: skip
    ev = await ctx.record("traverse_passage", actor_id=first, target_id=dest.id, payload=out, dice=dice or None,
                          inverse=inverse)  # fmt: skip
    return {**out, "event_id": ev.id}


def _arrive(ctx, heroes, dest: Entity, p: Passage, other: End, lane: int, inverse: list) -> tuple[int, int] | None:
    """Герои встают у прохода с той стороны: первый — на ту же полосу широкого края, остальные — рядом."""
    w = ctx.world
    if other.external:
        return None
    cells = endpoint_cells(w, dest.id, p.passage_ref)
    if not cells:
        return None
    target = cells[min(lane, len(cells) - 1)]
    inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(w.scene.state)})
    first_cell = None
    for hero in heroes:
        got = grid.free_cells_near(w, dest.id, grid.to_rel(w, dest.id, target), 1, hero.id)
        if got:
            grid.set_cell(w, hero.id, got[0])
            first_cell = first_cell or grid.to_master(w, dest.id, got[0])
    return first_cell


async def traverse(maker, preparer, dice_factory, campaign_id: str, hero_id: str, passage_ref: str):
    """Переход по действию игрока: подготовка принята → дождаться её вне транзакции → проверить и перейти."""
    from app.tools.runtime import flush_outbox, open_context

    async with maker() as s:
        c = await s.get(Campaign, campaign_id)
        ctx = await open_context(s, c, dice_factory(), turn_id=None, seat_id=None)
        inverse: list = []
        try:
            req = await begin(ctx, [hero_id], passage_ref, inverse)
        except ToolError as e:
            await s.rollback()
            return {"ok": False, "error": str(e)}, None, []
        await ctx.record("request_passage", actor_id=hero_id, target_id=req.dest_id,
                         payload={"passage_ref": passage_ref, "refs": list(req.refs)}, inverse=inverse,
                         hidden=True)  # fmt: skip
        await flush_outbox(s, ctx)
        await s.commit()
    if req.refs and preparer is not None:
        await preparer.settle(maker, campaign_id, list(req.refs))
    async with maker() as s:
        c = await s.get(Campaign, campaign_id)
        ctx = await open_context(s, c, dice_factory(), turn_id=None, seat_id=None)
        out = await finish(ctx, req)
        messages = await flush_outbox(s, ctx)
        await s.commit()
    return {"ok": True, **out}, ctx, messages
```

- [ ] **Step 4: Passing a passage does not lay new map links** (`app/tools/master/places.py`, начало `_connect`)

`move_heroes` и `relocate_scene` отмечают пройденный путь ссылкой `state.links`; у комплекса проходы заданы
blueprint, и лишняя ссылка «деревня → участок» стала бы ложным соседством.

```python
def _connect(ctx: ToolContext, a: Entity, b: Entity, inverse: list) -> None:
    """В свободном мире пройденный маршрут отмечается; в книге и в комплексе переходы заданы планом."""
    from app.core.layout import store

    if store.complex_of(a) or store.complex_of(b):
        return  # проходы комплекса заданы blueprint: переход не прокладывает нового пути
    ...  # прежнее тело без изменений
```

И в `test_traverse_from_outside_prepares_then_moves` добавить в конец:

```python
    from app.db.models import Entity

    links = run(settings, lambda s: s.get(Entity, village)).state.get("links") or []
    assert ids["road"] not in {x["to"] for x in links}
```

- [ ] **Step 5: Protocol and gateway**

`app/gateway/protocol.py` — рядом с `MapStepResult`:

```python
class MapTraverseResult(_Open):
    request_id: str | None
    ok: bool
```

и в словарь событий: `"map.traverse.result": MapTraverseResult,`.

`app/gateway/ws.py` — в docstring модуля добавить `map.traverse` к перечню событий и строку
«``map.traverse`` — герой зрителя проходит проходом комплекса (``map.traverse.result``, app/core/layout/transit.py).»;
в диспетчер после `map.step`:

```python
            if kind == "map.traverse":
                await _traverse(app, user, conn, payload)
                continue
```

и обработчик рядом с `_step`:

```python
async def _traverse(app, user: User, conn: Connection, payload: dict) -> None:
    """Герой зрителя проходит проходом комплекса: участок за ним сначала готовится, затем сервер заново проверяет
    проход и переводит героя. Ответ ``map.traverse.result`` — только этому сокету; схема у всех — по ``map.changed``."""
    from app.core.inspect import viewer_hero
    from app.core.layout import transit
    from app.tools.runtime import publish_changes

    request_id = payload.get("request_id")
    ref = payload.get("passage_ref")

    async def answer(body: dict) -> None:
        await conn.send(envelope("map.traverse.result", conn.campaign_id, {"request_id": request_id, **body}))

    if not isinstance(ref, str) or not 0 < len(ref) <= 64:
        await answer({"ok": False, "error": "passage_ref — строка"})
        return
    async with app.state.sessionmaker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id, payload.get("as_seat") or None)
        except NotFound as e:
            await answer({"ok": False, "error": str(e)})
            return
        hero = await viewer_hero(session, viewer)
        if hero is None:
            await answer({"ok": False, "error": "у тебя нет героя в этой кампании"})
            return
        hero_id = hero.id
    out, ctx, messages = await transit.traverse(
        app.state.sessionmaker, app.state.master.preparer, app.state.dice_factory, conn.campaign_id, hero_id, ref
    )
    await answer(out)
    if ctx is not None:
        await publish_changes(app.state.bus, ctx, messages)
        await app.state.bus.publish(conn.campaign_id, envelope("map.changed", conn.campaign_id, {}), None)
        await _publish_turn(app, ctx)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout_transit.py tests/test_ws.py tests/test_contract.py tests/test_map.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/core/layout/transit.py app/tools/master/places.py app/gateway/ws.py app/gateway/protocol.py tests/test_layout_transit.py
git commit -m "Переход между участками: сначала готовится назначение, потом сервер заново проверяет проход

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Переход мастера в ходе и геометрия при входе

**Files:**
- Modify: `app/core/layout/transit.py` (`enqueue`, `complete_queued`)
- Modify: `app/tools/master/places.py` (`traverse_passage`, `request_preparation`)
- Modify: `app/agents/master/finish.py:73-77` (`_narrate_turn`)
- Modify: `app/gateway/ws.py` (панель мастера: фоновое завершение очереди)
- Test: `tests/test_layout_turn.py`

**Interfaces:**
- Consumes: Task 11 `Request`, `begin`, `finish`.
- Produces: `transit.enqueue(ctx, req, inverse)`; `async transit.complete_queued(maker, preparer, dice_factory,
  campaign_id, bus=None) -> list[str]` (id событий перехода); инструмент мастера
  `traverse_passage{character_ids=[], passage_ref}` → готово — `{moved: True, ...}`, иначе
  `{queued: True, passage, note}` и refs в `ctx.operation_refs`; `request_preparation` добавляет ref геометрии участка
  в `ctx.operation_refs`. Очередь — `scene.state["transits"]`.

- [ ] **Step 1: Write the failing tests** — `tests/test_layout_turn.py`

```python
# ruff: noqa: F811
"""Переход мастера в ходе (спецификация 2026-10-12, §8): описание — только после зафиксированного перехода."""

from app.core.layout import store
from app.core.world_generation import storage
from app.db.models import Character, Event, Scene
from tests.game import party, run
from tests.layout_pilot import pilot_intent
from tests.test_layout_preparation import _activate, _areas
from tests.test_map import _ok, _play
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры хода
from tests.test_world_generation import _fast_retry, _prepare  # noqa: F401 — фикстура


def _temple(settings, cid):
    async def go(ctx):
        village = (await _ok(ctx, "create_location", {"name": "Деревня", "make_current": True}))["location_id"]
        temple = (await _ok(ctx, "create_location", {"name": "Старый храм"}))["location_id"]
        intent = pilot_intent(village).model_dump(mode="json")
        return temple, (await _ok(ctx, "prepare_complex", {"location_id": temple, "intent": intent}))["operation_ref"]

    temple, ref = _play(settings, cid, go)
    _prepare(settings, cid, ref)
    return {k: v.id for k, v in _areas(settings, temple).items()}


def test_turn_moves_through_passage_before_narration(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    cid, hid = c["id"], hero["id"]
    ids = _temple(settings, cid)
    llm.replies += [{"tool_calls": [("traverse_passage", {"passage_ref": "in_road_w"})]}, DONE,
                    {"text": "Пыльная дорога у храма."}]  # fmt: skip
    told = act(game_client, p1, cid, "Иду по дороге к храму")
    assert told["kind"] == "narration"
    assert run(settings, lambda s: s.get(Character, hid)).location_id == ids["road"]
    assert not (run(settings, lambda s: s.get(Scene, cid)).state or {}).get("transits")
    moved = [e for e in rows(settings, Event, Event.tool == "traverse_passage") if e.payload.get("moved")]
    assert len(moved) == 1
    assert "Дорога у храма" in str(llm.requests[-1]["messages"])  # описание видит уже новый участок


def test_ready_destination_moves_inside_the_tool(client, admin, settings):
    from tests.game import import_base, quiet

    import_base(settings)
    c, _heads, hero = party(client, admin)
    quiet(client)
    cid, hid = c["id"], hero["id"]
    ids = _temple(settings, cid)
    _prepare(settings, cid, _activate(settings, cid, ids["road"]))

    async def go(ctx):
        out = await _ok(ctx, "traverse_passage", {"passage_ref": "in_road_w"})
        return out, sorted(ctx.operation_refs)

    out, refs = _play(settings, cid, go)
    assert out["moved"] and out["area_id"] == ids["road"] and refs == []


def test_move_into_area_requests_its_geometry(client, admin, settings):
    from tests.game import import_base, quiet

    import_base(settings)
    c, _heads, hero = party(client, admin)
    quiet(client)
    cid, hid = c["id"], hero["id"]
    ids = _temple(settings, cid)

    async def go(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["brook"]})
        geo = await storage.find(ctx.session, cid, ids["brook"], "location_geometry")
        return geo.id, set(ctx.operation_refs), store.complex_of(ctx.world.entities[ids["brook"]])

    geo, refs, cx = _play(settings, cid, go)
    assert geo in refs and cx["area_ref"] == "brook"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_layout_turn.py -q`
Expected: FAIL — `traverse_passage` не найден в реестре.

- [ ] **Step 3: Queue helpers in `app/core/layout/transit.py`**

В импорт моделей добавить `Scene`: `from app.db.models import Campaign, Entity, Scene`. Затем:

```python
def enqueue(ctx, req: Request, inverse: list) -> None:
    """Переход хода ждёт подготовки: ход завершит его после ``settle``, до описания."""
    sc = ctx.world.scene
    inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(sc.state)})
    queued = [*((sc.state or {}).get(QUEUE) or []), {**req.to_json(), "turn_id": ctx.turn_id}]
    sc.state = {**(sc.state or {}), QUEUE: queued}


async def complete_queued(maker, preparer, dice_factory, campaign_id: str, bus=None) -> list[str]:
    """Завершить отложенные переходы кампании: дождаться их подготовок, затем каждый — своей транзакцией.
    Возвращает id событий состоявшихся переходов; несостоявшийся оставляет системную заметку."""
    from app.gateway.events import envelope
    from app.tools.runtime import flush_outbox, open_context, publish_changes

    async with maker() as s:
        sc = await s.get(Scene, campaign_id)
        queued = list(((sc.state or {}) if sc is not None else {}).get(QUEUE) or [])
    if not queued:
        return []
    refs = sorted({r for q in queued for r in q.get("refs") or []})
    if refs and preparer is not None:
        await preparer.settle(maker, campaign_id, refs)
    done: list[str] = []
    for item in queued:
        async with maker() as s:
            c = await s.get(Campaign, campaign_id)
            ctx = await open_context(s, c, dice_factory(), turn_id=item.get("turn_id"), seat_id=None)
            sc = ctx.world.scene
            left = [q for q in (sc.state or {}).get(QUEUE) or [] if q != item]
            sc.state = {k: v for k, v in {**(sc.state or {}), QUEUE: left}.items() if k != QUEUE or left}
            out = await finish(ctx, Request.from_json(item))
            if out["moved"]:
                done.append(out["event_id"])
            else:
                ctx.outbox.append({"kind": "system", "content": f"Переход не состоялся: {out['reason']}"})
            messages = await flush_outbox(s, ctx)
            await s.commit()
        if bus is not None:
            await publish_changes(bus, ctx, messages)
            await bus.publish(campaign_id, envelope("map.changed", campaign_id, {}), None)
    return done
```

- [ ] **Step 4: The master tool and geometry on entry** (`app/tools/master/places.py`)

В `request_preparation`, первыми строками тела:

```python
    from app.core.layout import store as layout_store

    geo = await layout_store.request_geometry(ctx, loc)
    if geo is not None:
        ctx.operation_refs.add(geo)  # ход дождётся геометрии участка до описания
```

Новый инструмент после `move`:

```python
class TraverseArgs(BaseModel):
    character_ids: list[str] = Field(
        default_factory=list, description="кто проходит; пусто — все герои, что стоят там же, где сцена"
    )
    passage_ref: str = Field(
        min_length=1, max_length=64, description="проход комплекса из таблицы сцены («проход p_…» у выхода)"
    )


@tool(
    "traverse_passage",
    "Герои проходят проходом комплекса — дверью, аркой, лестницей или свободным краем поля — в соседний участок. "
    "Участок за проходом сначала готовится; описывай его только после перехода. Закрытую дверь сначала открывают.",
    TraverseArgs,
    ids={"character_ids": "characters"},
)
async def traverse_passage(ctx: ToolContext, a: TraverseArgs) -> dict:
    from app.core.layout import transit

    w = ctx.world
    if a.character_ids:
        heroes = [_character(ctx, cid) for cid in a.character_ids]
    else:
        heroes = [c for c in w.characters.values() if c.status in PLAYABLE and w.place_of(c) == w.scene.location_id]
    if not heroes:
        raise ToolError("некому идти: назови героев в character_ids")
    inverse: list = []
    req = await transit.begin(ctx, [h.id for h in heroes], a.passage_ref, inverse)
    if not req.refs:  # участок уже готов: переход сразу, в этом же ходе
        out = await transit.finish(ctx, req, inverse)
        if not out["moved"]:
            raise ToolError(out["reason"])
        return out
    transit.enqueue(ctx, req, inverse)
    ctx.operation_refs.update(req.refs)
    payload = {"queued": True, "passage_ref": a.passage_ref, "refs": list(req.refs)}
    await ctx.record("traverse_passage", target_id=req.dest_id, payload=payload, inverse=inverse, hidden=True)
    return {"queued": True, "passage": a.passage_ref, "note": "участок за проходом готовится; герои перейдут до описания"}
```

- [ ] **Step 5: Complete queued transits in the turn** (`app/agents/master/finish.py`)

В `_narrate_turn` сразу после строки `cp["unavailable"] = await self._settle_preparation(cid, refs) if refs else []`:

```python
                        from app.core.layout import transit

                        done = await transit.complete_queued(self.maker, self.preparer, self.dice_factory, cid)
                        if done:
                            cp["event_ids"] = [*(cp.get("event_ids") or []), *done]
```

В `app/gateway/ws.py`, обработчик инструмента с панели мастера — перед `if ctx.operation_refs:`:

```python
        if (ctx.world.scene.state or {}).get("transits"):  # переход с панели: завершить после подготовки, в фоне
            from app.core.layout import transit

            _background(transit.complete_queued(app.state.sessionmaker, app.state.master.preparer,
                                                app.state.dice_factory, conn.campaign_id, bus=app.state.bus))  # fmt: skip
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_layout_turn.py tests/test_world_generation.py tests/test_world_transactions.py tests/test_master.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/core/layout/transit.py app/tools/master/places.py app/agents/master/finish.py app/gateway/ws.py tests/test_layout_turn.py
git commit -m "Мастер проводит героев проходом комплекса; описание ждёт зафиксированного перехода

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Пилот целиком, документ поставки и полная проверка

**Files:**
- Test: `tests/test_layout_pilot.py`
- Create: `docs/location-maps-delivery1.md`

**Interfaces:**
- Consumes: всё выше. Produces: сквозной тест приёмки поставки 1 и документ для планов поставок 2–3.

- [ ] **Step 1: Write the end-to-end pilot test** — `tests/test_layout_pilot.py`

```python
# ruff: noqa: F811
"""Пилот поставки 1 (спецификация 2026-10-12, §10): поле → храм → назад, устройство места сохраняется."""

from app.core import sketch
from app.core.layout.contracts import terrain_cells
from app.core.layout import store
from app.db.models import Character, Entity, WorldGenerationState
from tests.game import run
from tests.test_layout_passages import _built
from tests.test_layout_transit import _go
from tests.test_map import _ok, _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура

WGS = WorldGenerationState


def test_pilot_field_temple_and_back(client, admin, settings):
    cid, heads, hid, village, temple, ids = _built(client, admin, settings)
    head = heads[0]
    assert _go(client, head, cid, "in_road_w")["moved"]

    async def open_doors(ctx):
        await _ok(ctx, "edit_sketch", {"action": "open", "target": "Двери храма", "location_id": ids["road"]})

    _play(settings, cid, open_doors)
    for ref in ("p_narthex", "p_nave", "p_chapel"):
        out = _go(client, head, cid, ref)
        assert out["ok"] and out["moved"], out
    assert run(settings, lambda s: s.get(Character, hid)).location_id == ids["chapel"]
    layouts_before = len(rows(settings, WGS))
    ids_before = dict(ids)

    for ref in ("p_chapel", "p_nave", "p_narthex", "p_brook"):
        assert _go(client, head, cid, ref)["moved"]
    assert run(settings, lambda s: s.get(Character, hid)).location_id == ids["brook"]
    assert len(rows(settings, WGS)) == layouts_before  # возвращение не создаёт новых подготовок
    root = run(settings, lambda s: s.get(Entity, temple))
    assert store.area_ids(root) == ids_before

    road = run(settings, lambda s: s.get(Entity, ids["road"])).state["sketch"]
    brook = run(settings, lambda s: s.get(Entity, ids["brook"])).state["sketch"]
    assert road["environment"] == "outdoor" and not road["walls"] and "mask" not in road
    meanings = {(g["side"], g["meaning"]) for g in road["edges"]}
    assert ("e", "continuation") in meanings and ("w", "boundary") in meanings
    bp = store.blueprint_of(root)
    assert {(11, 3), (11, 4)} <= terrain_cells(bp.area("road"), "road")
    assert {(0, 3), (0, 4)} <= terrain_cells(bp.area("brook"), "road")
    assert any(t["kind"] == "bridge" for t in road["terrain"]) and brook["blueprint"]["area_ref"] == "brook"

    nave = run(settings, lambda s: s.get(Entity, ids["nave"])).state["sketch"]
    assert nave["walls"] == [[1, 2], [1, 6], [6, 2], [6, 6]]  # колонны — геометрия
    door = next(x for x in nave["exits"] if x["passage_ref"] == "p_nave")
    assert door["side"] == "s" and sketch.check(nave, {x["to"] for x in nave["exits"] if x["to"]}) == []
```

- [ ] **Step 2: Run the pilot test**

Run: `uv run pytest tests/test_layout_pilot.py -q`
Expected: PASS. Падение здесь — признак расхождения между задачами (имена, координаты); чинить в задаче-владельце.

- [ ] **Step 3: Write `docs/location-maps-delivery1.md`**

```markdown
# Генерация локаций, поставка 1: blueprint, геометрия и переходы

Спецификация: docs/superpowers/specs/2026-10-12-generative-location-maps-design.md (§9, поставка 1).

## Что есть

- **Замысел** (`app/core/layout/intent.py`): части, связи, подходы, полосы рельефа. Команда ведущего
  `prepare_complex` принимает его для места и возвращает квитанцию `location_layout`.
- **Blueprint** (`contracts.py`): участки с локальными координатами и смещением на плане уровня, проходы с двумя
  концами, края открытых участков, рельеф, привязки зацепок и обязательные участки. Хранится в `state.blueprint`
  корня; `state.areas` — реальные id участков; `state.passages` — живое состояние проходов (одно на обе стороны).
- **Провайдер** (`provider.py`): детерминированная раскладка и упрощённая цепочка как fallback; обе проверяются
  `validation.validate`. Не выполнены обязательства — `blocked/layout_unsatisfiable`.
- **Геометрия** (`geometry.py`): эскиз участка кодом — маска пола, твёрдые детали как стены, проходы с клетками,
  края, рельеф, материал. Фаза `location_geometry`; ручной эскиз мастера сохраняется (`manual_preserved`).
- **Маска пола** — общая мера непроходимости шага, пути, прямой видимости и досягаемости (`sketch.solid_cells`).
- **Обстановка** (`furnish.py`): объекты подготовки `location_initial` встают связанными деталями на свободные
  клетки, не у проходов; обстановка ждёт геометрию своего участка.
- **Переход** (`transit.py`): `begin` → подготовка назначения → `finish` с повторной проверкой. Игрок —
  `map.traverse`; мастер — `traverse_passage` (в ходе — через очередь `scene.state.transits`, до описания).
- **Соседство** (`topology.location_exits`): участки связаны проходами, не вложенностью; тайный проход соседства
  не даёт, пока не раскрыт.

## Чего нет (поставки 2–3)

SVG-слои и узоры, композиция открытых участков на одной карте, память карты по героям (сейчас — `visited_by` и
общий флаг `hidden`), текстовый provider и лимит его вызовов, интеграция с архитектором, подготовка первой сцены и
вперёд, учёт суммарных расходов, дальние ориентиры.

## Решения поставки

- Переход мастера через `move` в участок остаётся (телепорт, падение); правильный путь — `traverse_passage`.
  `move` в участок запрашивает его геометрию, и ход ждёт её до описания.
- Зацепка корня, которой нет в замысле, отдаётся входному участку (не теряется).
- Состояние двери меняет `edit_sketch` с действием open/close/lock/unlock/reveal/hide; удалить или переименовать
  проход нельзя — он общий для двух участков; `sketch_place` поверх эскиза из blueprint запрещён.
```

- [ ] **Step 4: Run lint and the whole suite**

Run: `uv run ruff check app tests && uv run ruff format --check app tests`
Expected: без замечаний (исправить и повторить, если есть).

Run: `uv run pytest -q -n auto`
Expected: все тесты проходят (базовый уровень до поставки — 721 passed; новые добавляются). Отдельно убедиться,
что не изменилось поведение книжных карт: `uv run pytest tests/test_adventure.py tests/test_modules.py tests/test_map.py tests/test_sketch.py tests/test_grid.py tests/test_world_objects_reach.py -q`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_layout_pilot.py docs/location-maps-delivery1.md
git commit -m "Пилот храма и поля проходит туда и обратно; итог первой поставки карт локаций

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Порядок и зависимости

```
1 маска ─┬─► 3 геометрия ─► 4 проверка ─► 5 provider ─► 6 фазы/store ─► 7 исполнители ─┬─► 8 проходы ─► 9 соседство ─┐
2 контракты ┘                                                                          └─► 10 обстановка ───────────┤
                                                                                         11 переход ◄────────────────┘
                                                                                         12 ход мастера ◄── 11
                                                                                         13 пилот ◄── всё
```

Выполнять в изолированном worktree (`superpowers:using-git-worktrees`); в основной рабочей копии есть чужие правки
(`docs/README.md`, неотслеживаемые спеки) — их не трогать и не коммитить.
