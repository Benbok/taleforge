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
class ObjectSlot:
    slot_ref: str
    role: str
    cells: tuple[Rect, ...]
    detail_ref: str | None = None
    hidden: bool = False
    max_cols: int = 1
    max_rows: int = 1


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
    scene_profile: str | None = None
    object_slots: tuple[ObjectSlot, ...] = ()


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
        if not isinstance(d, dict):
            raise LayoutError([f"blueprint: ожидался объект, получено {type(d).__name__}"])
        try:
            version = int(d.get("schema_version") or 0)
            if version != SCHEMA_VERSION:
                raise LayoutError([f"blueprint: неизвестная версия схемы {d.get('schema_version')}"])
            bp = cls._parse(d)
            if not -(2**31) <= bp.seed < 2**31:
                raise LayoutError(["blueprint: seed за пределами int32"])
            return bp
        except LayoutError:
            raise
        except (KeyError, TypeError, ValueError, OverflowError, IndexError, AttributeError) as e:
            raise LayoutError([f"blueprint: {type(e).__name__}: {e}"]) from e

    @classmethod
    def _parse(cls, d: dict[str, Any]) -> Blueprint:
        def rects(xs) -> tuple[Rect, ...]:
            return tuple(tuple(int(v) for v in x) for x in xs or ())  # type: ignore[misc]

        def end(e: dict) -> End:
            return End(
                e.get("area_ref"), e.get("side"), int(e.get("start") or 0), int(e.get("width") or 1), e.get("place_id")
            )

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
                scene_profile=a.get("scene_profile"),
                object_slots=tuple(ObjectSlot(
                    x["slot_ref"], x["role"], rects(x["cells"]), x.get("detail_ref"),
                    bool(x.get("hidden")), int(x.get("max_cols", 1)), int(x.get("max_rows", 1)),
                ) for x in a.get("object_slots") or ()),
                details=tuple(
                    Detail(
                        x["detail_ref"],
                        x["name"],
                        x.get("kind") or "object",
                        rects(x["cells"]),
                        bool(x.get("solid")),
                        bool(x.get("hidden")),
                    )
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
                p["passage_ref"],
                p["kind"],
                p["name"],
                p.get("public_name") or p["name"],
                (end(p["ends"][0]), end(p["ends"][1])),
                p.get("state") or "open",
                bool(p.get("hidden")),
            )
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
