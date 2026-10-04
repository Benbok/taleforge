"""Позиции в сцене (просьба Arty, 2026-09-29): где стоит каждый участник, на какой высоте и за каким укрытием.

Сетки нет. Позиция — зона дальности от центра отряда (вплотную 5, близко 30, далеко 120 футов), сторона света и
высота. Расстояние между двумя участниками — по прямой между такими точками, округлённое до 5 футов (минимум 5).

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

from app.core.world import ZONE_FT

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

    def xy(self, fallback_bearing: str | None) -> tuple[float, float]:
        if self.zone is None:
            return 0.0, 0.0
        r = ZONE_FT.get(self.zone, 30)
        deg = BEARING_DEG.get(self.bearing or fallback_bearing or "n", 0)
        return r * math.sin(math.radians(deg)), r * math.cos(math.radians(deg))

    def public(self) -> dict[str, Any]:
        return {"zone": self.zone, "bearing": self.bearing, "elevation": self.elevation, "cover": self.cover}


def hero_positions(scene) -> dict[str, dict]:
    return dict((scene.state or {}).get("positions") or {})


def pos_of(world, actor_id: str) -> Pos:
    if actor_id in world.characters:
        p = hero_positions(world.scene).get(actor_id) or {}
        return Pos(p.get("zone"), p.get("bearing"), p.get("elevation") or "ground", p.get("cover") or "none")
    en = world.entities[actor_id]
    st = en.state or {}
    return Pos(en.zone, st.get("bearing"), st.get("elevation") or "ground", st.get("cover") or "none")


def _round5(ft: float) -> int:
    return max(5, int(5 * round(ft / 5)))


def distance(a: Pos, b: Pos, *, both_creatures: bool = False) -> int:
    """Футы между двумя позициями."""
    dz = ELEVATION_FT.get(a.elevation, 0) - ELEVATION_FT.get(b.elevation, 0)
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
