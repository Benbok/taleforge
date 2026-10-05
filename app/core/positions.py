"""Позиции в сцене (просьба Arty, 2026-09-29): где стоит каждый участник, на какой высоте и за каким укрытием.

Позиция — клетка по 5 футов (решение Arty 2026-10-05: бой на сетке) или, пока мастер клетку не назначил, зона
дальности от центра отряда (вплотную 5, близко 30, далеко 120 футов) со стороной света. Расстояние между двумя
клетками — по правилам сетки SRD: каждая клетка, и по диагонали тоже, — 5 футов. Между клеткой и зоной или двумя
зонами — по прямой между точками, округлённое до 5 футов (минимум 5).

- Клетка хранится относительно строя отряда: (0, 0) — где стоит строй, восток и юг положительные. Мастер называет
  клетки так же, а в месте с эскизом — от северо-западного угла эскиза (app/core/sketch.py); перевод — ``to_rel``
  и ``to_master``. Зона у участника с клеткой выводится из расстояния до строя.

- Герой без позиции стоит в центре отряда; тогда до существа ровно его зона, как было до позиций. Позиции героев
  лежат в ``scenes.state["positions"]`` и сбрасываются, когда сцена переходит в другое место.
- Существо: зона в ``entities.zone``, сторона, высота и укрытие — в ``entities.state``.
- У кого не указана сторона, считаем, что он в той же стороне, что и второй участник: мастер не сказал иначе.
- Высота: низ (яма, трюм) −10 футов, земля 0, возвышение (балкон, гребень) +15. Правил преимущества за высоту в
  SRD нет: высота меняет только расстояние.
- Укрытие по SRD: половинное +2 к КД, на три четверти +5, полное — цель нельзя атаковать напрямую.
- Области (облако газа, огонь, туман) — объекты сцены с ``state.area``: центр, радиус и срок до игрового времени.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.core.world import PLAYABLE, ZONE_FT

BEARING_DEG = {"n": 0, "ne": 45, "e": 90, "se": 135, "s": 180, "sw": 225, "w": 270, "nw": 315}
ELEVATION_FT = {"low": -10, "ground": 0, "high": 15}
ELEVATION_NAMES = {"low": "внизу", "ground": "на земле", "high": "на возвышении"}
COVER_AC = {"none": 0, "half": 2, "three_quarters": 5}
COVER_NAMES = {"none": "без укрытия", "half": "половинное укрытие", "three_quarters": "укрытие на три четверти",
               "total": "полное укрытие"}  # fmt: skip


@dataclass
class Pos:
    zone: str | None = None  # None — в центре отряда
    bearing: str | None = None
    elevation: str = "ground"
    cover: str = "none"
    cell: tuple[int, int] | None = None  # клетка от строя отряда: восток и юг положительные

    def xy(self, fallback_bearing: str | None) -> tuple[float, float]:
        if self.cell is not None:
            return self.cell[0] * 5.0, -self.cell[1] * 5.0
        if self.zone is None:
            return 0.0, 0.0
        r = ZONE_FT.get(self.zone, 30)
        deg = BEARING_DEG.get(self.bearing or fallback_bearing or "n", 0)
        return r * math.sin(math.radians(deg)), r * math.cos(math.radians(deg))

    def public(self) -> dict[str, Any]:
        out = {"zone": self.zone, "bearing": self.bearing, "elevation": self.elevation, "cover": self.cover}
        if self.cell is not None:
            out["cell"] = list(self.cell)
        return out


def _cell(v: Any) -> tuple[int, int] | None:
    return (int(v[0]), int(v[1])) if isinstance(v, list | tuple) and len(v) == 2 else None


def zone_of_cell(cell: tuple[int, int]) -> str:
    """Зона для участника на клетке: по расстоянию сетки до строя отряда."""
    ft = max(abs(cell[0]), abs(cell[1])) * 5
    return "melee" if ft <= 5 else "near" if ft <= 30 else "far"


def bearing_of_cell(cell: tuple[int, int]) -> str | None:
    """Сторона света клетки от строя: для текстов и старых раскладок, где клетки нет."""
    c, r = cell
    if c == 0 and r == 0:
        return None
    deg = math.degrees(math.atan2(c, -r)) % 360
    return min(BEARING_DEG, key=lambda b: min(abs(BEARING_DEG[b] - deg), 360 - abs(BEARING_DEG[b] - deg)))


def _sketch(world, place: str | None) -> dict | None:
    from app.core import sketch

    return sketch.of_place(world.entities.get(place or ""), world.catalog, world.entities)


def anchor(world, place: str | None, sk: dict | None = None) -> tuple[int, int]:
    """Где строй отряда в координатах мастера: клетка ``party`` эскиза места или (0, 0) без эскиза."""
    sk = sk if sk is not None else _sketch(world, place)
    return (int(sk["party"][0]), int(sk["party"][1])) if sk else (0, 0)


def to_rel(world, place: str | None, cell: list[int] | tuple[int, int]) -> tuple[int, int]:
    ax, ay = anchor(world, place)
    return int(cell[0]) - ax, int(cell[1]) - ay


def to_master(world, place: str | None, cell: tuple[int, int]) -> tuple[int, int]:
    ax, ay = anchor(world, place)
    return cell[0] + ax, cell[1] + ay


def cell_problem(
    world, place: str | None, cell: tuple[int, int], actor_id: str | None = None, sk: dict | None = None
) -> str | None:
    """Почему на клетку (от строя) нельзя встать: за краем места, стена или предмет эскиза, там уже кто-то стоит."""
    sk = sk if sk is not None else _sketch(world, place)
    ax, ay = anchor(world, place, sk)
    c, r = cell[0] + ax, cell[1] + ay
    shown = [c, r]
    if sk is not None:
        if not (0 <= c < sk["cols"] and 0 <= r < sk["rows"]):
            return f"клетка {shown} за краем места {sk['cols']}×{sk['rows']}"
        if [c, r] in (sk.get("walls") or []):
            return f"клетка {shown} — стена"
        for f in sk.get("features") or []:
            if any(c0 <= c <= c1 and r0 <= r <= r1 for c0, r0, c1, r1 in f["cells"]):
                return f"на клетке {shown} стоит «{f['name']}»"
    for aid, name in _standing(world, place):
        if aid == actor_id:
            continue
        here = pos_of(world, aid).cell
        if (here if here is not None else ((0, 0) if aid in world.characters else None)) == cell:
            return f"клетка {shown} занята: там {name}"
    return None


def floor_problem(world, place: str | None, cell: tuple[int, int], wall_ok: bool = False) -> str | None:
    """Почему на клетку (от строя) нельзя положить вещь: за краем места или стена. Вещь может лежать на предмете
    эскиза (в сене на телеге) и под ногами участника; примета (``wall_ok``) может и висеть на стене."""
    sk = _sketch(world, place)
    if sk is None:
        return None
    ax, ay = anchor(world, place, sk)
    c, r = cell[0] + ax, cell[1] + ay
    if not (0 <= c < sk["cols"] and 0 <= r < sk["rows"]):
        return f"клетка {[c, r]} за краем места {sk['cols']}×{sk['rows']}"
    if not wall_ok and [c, r] in (sk.get("walls") or []):
        return f"клетка {[c, r]} — стена"
    return None


def _standing(world, place: str | None) -> list[tuple[str, str]]:
    """Кто стоит в месте: герои в игре и живые существа. Герой без клетки — в строю отряда, на (0, 0)."""
    out = [
        (h.id, h.name) for h in world.characters.values() if h.status in PLAYABLE and world.actor_place(h.id) == place
    ]
    out += [
        (e.id, e.name)
        for e in world.entities.values()
        if e.kind == "creature" and e.location_id == place and not (e.state or {}).get("dead")
    ]
    return out


def free_cells_near(
    world, place: str | None, cell: tuple[int, int], n: int, actor_id: str | None = None
) -> list[tuple[int, int]]:
    """``n`` свободных клеток (от строя), начиная с ``cell`` и дальше кольцами вокруг неё. В месте с эскизом
    начало сперва сдвигается внутрь места."""
    sk = _sketch(world, place)
    if sk is not None:
        ax, ay = anchor(world, place, sk)
        cell = (min(max(cell[0] + ax, 0), sk["cols"] - 1) - ax, min(max(cell[1] + ay, 0), sk["rows"] - 1) - ay)
    out: list[tuple[int, int]] = []
    for d in range(0, 31):
        for dr in range(-d, d + 1):
            for dc in range(-d, d + 1):
                c = (cell[0] + dc, cell[1] + dr)
                if max(abs(dc), abs(dr)) != d or c in out:
                    continue
                if cell_problem(world, place, c, actor_id, sk) is None:
                    out.append(c)
                    if len(out) == n:
                        return out
    return out


DEPLOY_CELLS = {"melee": 1, "near": 6, "far": 12}  # как рисует схема (web/src/game/map.ts ZONE_CELLS)


def cell_from_zone(p: Pos) -> tuple[int, int]:
    """Клетка по зоне и стороне — там, где схема рисовала участника до сетки: «далеко» у края схемы, в 60 футах."""
    if p.zone is None:
        return 0, 0
    n = DEPLOY_CELLS.get(p.zone, 6)
    deg = math.radians(BEARING_DEG.get(p.bearing or "n", 0))
    return round(n * math.sin(deg)), round(-n * math.cos(deg))


def set_cell(world, actor_id: str, cell: tuple[int, int] | None) -> None:
    """Ставит участника на клетку (от строя) или снимает с неё; зона и сторона выводятся из клетки. Обратную запись
    для отмены делает вызывающий."""
    if actor_id in world.characters:
        sc = world.scene
        positions = hero_positions(sc)
        p = dict(positions.get(actor_id) or {})
        if cell is None:
            p.pop("cell", None)
        else:
            p.update(cell=list(cell), zone=zone_of_cell(cell), bearing=bearing_of_cell(cell))
        positions[actor_id] = p
        sc.state = {**(sc.state or {}), "positions": positions}
    else:
        en = world.entities[actor_id]
        st = dict(en.state or {})
        if cell is None:
            st.pop("cell", None)
        else:
            st["cell"] = list(cell)
            en.zone = zone_of_cell(cell)
            b = bearing_of_cell(cell)
            if b:
                st["bearing"] = b
        en.state = st
    world.invalidate(actor_id)


def grid_deploy(world, place: str | None, ids: list[str]) -> list[tuple[str, tuple[int, int]]]:
    """Начало боя: каждый участник без клетки встаёт на свою. Герои — у строя отряда, существа — у точки своей зоны
    и стороны. Возвращает, кто куда встал (клетки от строя)."""
    placed = []
    heroes = [i for i in ids if i in world.characters and world.actor_place(i) == place]
    foes = [i for i in ids if i in world.entities and world.entities[i].location_id == place]
    for aid in heroes + foes:
        p = pos_of(world, aid)
        if p.cell is not None:
            continue
        start = (0, 0) if aid in world.characters and p.zone is None else cell_from_zone(p)
        got = free_cells_near(world, place, start, 1, aid)
        if got:
            set_cell(world, aid, got[0])
            placed.append((aid, got[0]))
    return placed


def hero_positions(scene) -> dict[str, dict]:
    return dict((scene.state or {}).get("positions") or {})


def pos_of(world, actor_id: str) -> Pos:
    if actor_id in world.characters:
        p = hero_positions(world.scene).get(actor_id) or {}
        return Pos(
            p.get("zone"),
            p.get("bearing"),
            p.get("elevation") or "ground",
            p.get("cover") or "none",
            _cell(p.get("cell")),
        )
    en = world.entities[actor_id]
    st = en.state or {}
    return Pos(
        en.zone, st.get("bearing"), st.get("elevation") or "ground", st.get("cover") or "none", _cell(st.get("cell"))
    )


def _round5(ft: float) -> int:
    return max(5, int(5 * round(ft / 5)))


def _grid_cell(p: Pos) -> tuple[int, int] | None:
    """Клетка для счёта по сетке: своя или, у стоящего в строю отряда, клетка строя (0, 0)."""
    return p.cell if p.cell is not None else (0, 0) if p.zone is None else None


def wall_between(world, a_id: str, b_id: str) -> bool:
    """Стоит ли стена эскиза на прямой между двумя участниками на сетке одного места: атаке и заклинанию
    нужна прямая видимость. Луч идёт от центра клетки к центру; клетки самих участников не считаются.
    Без эскиза, без клеток или в разных местах — стен не знаем, не мешают."""
    place = world.actor_place(a_id)
    if place is None or place != world.actor_place(b_id):
        return False
    sk = _sketch(world, place)
    walls = {tuple(x) for x in (sk or {}).get("walls") or []}
    if not walls:
        return False
    ac, bc = _grid_cell(pos_of(world, a_id)), _grid_cell(pos_of(world, b_id))
    if ac is None or bc is None:
        return False
    ax, ay = anchor(world, place, sk)
    (x0, y0), (x1, y1) = (ac[0] + ax, ac[1] + ay), (bc[0] + ax, bc[1] + ay)
    n = 4 * max(abs(x1 - x0), abs(y1 - y0))
    prev = (x0, y0)
    for i in range(1, n + 1):
        t = i / n
        cell = (math.floor(x0 + (x1 - x0) * t + 0.5), math.floor(y0 + (y1 - y0) * t + 0.5))
        if cell not in ((x0, y0), (x1, y1)) and cell in walls:
            return True
        if corner_wall(prev, cell[0] - prev[0], cell[1] - prev[1], walls):
            return True
        prev = cell
    return False


def corner_wall(at: tuple[int, int], dc: int, dr: int, walls: set) -> bool:
    """Шаг по диагонали из клетки ``at`` (координаты мастера) упирается в стык двух стен, сходящихся углом."""
    return bool(dc and dr) and (at[0] + dc, at[1]) in walls and (at[0], at[1] + dr) in walls


def distance(a: Pos, b: Pos, *, both_creatures: bool = False) -> int:
    """Футы между двумя позициями."""
    dz = ELEVATION_FT.get(a.elevation, 0) - ELEVATION_FT.get(b.elevation, 0)
    ac, bc = _grid_cell(a), _grid_cell(b)
    if ac is not None and bc is not None and (a.cell is not None or b.cell is not None):
        flat = max(abs(ac[0] - bc[0]), abs(ac[1] - bc[1])) * 5.0  # сетка SRD: диагональ тоже 5 футов
        if flat >= abs(dz):
            return max(5, int(flat))
        return _round5(math.hypot(flat, dz))
    if both_creatures and not (a.bearing and b.bearing):
        flat = 30.0  # двух существ без сторон мастер не расставил: прежнее «где-то рядом»
    elif a.zone is None and b.zone is None:
        flat = 0.0
    else:
        ax, ay = a.xy(b.bearing)
        bx, by = b.xy(a.bearing)
        flat = math.hypot(ax - bx, ay - by)
    if flat == 0 and dz == 0:
        return 5  # герои в центре отряда стоят рядом
    return _round5(math.hypot(flat, dz))


def point_distance(p: Pos, center: Pos) -> float:
    """Расстояние по земле от позиции до центра области (высоту область не учитывает)."""
    ax, ay = p.xy(center.bearing)
    bx, by = center.xy(p.bearing)
    return math.hypot(ax - bx, ay - by)


def active_areas(world, place: str | None = None) -> list:
    """Действующие области в местах, где стоят герои (или в одном месте ``place``)."""
    now = world.scene.game_time
    places = [place] if place else world.scene_places()
    out = []
    for e in world.entities.values():
        area = (e.state or {}).get("area")
        if not area or e.location_id not in places:
            continue
        if area.get("expires_at") is not None and now >= int(area["expires_at"]):
            continue
        out.append(e)
    return out


def area_center(e) -> Pos:
    return Pos(e.zone, (e.state or {}).get("bearing"))


def inside(world, area_entity, actor_id: str) -> bool:
    if world.actor_place(actor_id) != area_entity.location_id:
        return False  # область в другом месте: разделившийся отряд её не касается
    r = int(((area_entity.state or {}).get("area") or {}).get("radius_ft", 10))
    return point_distance(pos_of(world, actor_id), area_center(area_entity)) <= r


def areas_at(world, actor_id: str) -> list:
    return [e for e in active_areas(world) if inside(world, e, actor_id)]
