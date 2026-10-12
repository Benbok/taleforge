"""Персональная память геометрии карты.

Снимок намеренно отделён от ``Knowledge.observed_snapshot``: карточка знания
описывает сущность, а здесь хранится только стабильная геометрия участка,
которую конкретный герой уже видел.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select

from app.core import sketch
from app.db.models import MapMemory

_SKETCH_FIELDS = (
    "shape",
    "cols",
    "rows",
    "party",
    "walls",
    "mask",
    "edges",
    "terrain",
    "material",
    "environment",
    "exits",
    "features",
)


def _clean_sketch(
    raw: dict[str, Any], discovered_passages: frozenset[tuple[str, str]], root_id: str = ""
) -> dict[str, Any]:
    """Оставить в памяти только физическую геометрию и уже открытые подходы."""
    result = {key: copy.deepcopy(raw[key]) for key in _SKETCH_FIELDS if key in raw}
    root_id = str((raw.get("blueprint") or {}).get("root_id") or root_id)
    exits: list[dict[str, Any]] = []
    for original in raw.get("exits") or []:
        item = {
            key: copy.deepcopy(value)
            for key, value in original.items()
            if key in {"name", "side", "at", "kind", "state", "width", "cells", "passage_ref"}
        }
        ref = item.get("passage_ref")
        if ref and (root_id, str(ref)) not in discovered_passages:
            item.pop("to", None)
            item.pop("beyond", None)
            item.pop("passage_ref", None)
        exits.append(item)
    result["exits"] = exits
    features: list[dict[str, Any]] = []
    for original in raw.get("features") or []:
        if original.get("entity_id"):
            continue
        features.append(
            {
                key: copy.deepcopy(value)
                for key, value in original.items()
                if key in {"name", "kind", "cells", "cover", "access_sides"} and value is not None
            }
        )
    result["features"] = features
    return result


def static_snapshot(
    place: Any,
    root: Any,
    blueprint: dict[str, Any] | None,
    entities: dict[str, Any],
    *,
    discovered_passages: frozenset[tuple[str, str]] = frozenset(),
    revealed: frozenset[str] = frozenset(),
) -> dict[str, Any] | None:
    """Собрать детерминированный снимок без БД, времени и сетевых вызовов."""
    if place is None:
        return None
    raw = sketch.of_place(place, None, entities)
    if not isinstance(raw, dict) or not raw.get("cols"):
        return None
    complex_state = (place.state or {}).get("complex") or {}
    root_id = str(complex_state.get("root_id") or getattr(root, "id", ""))
    geometry = _clean_sketch(raw, discovered_passages, root_id)
    return {
        "schema_version": 1,
        "location_id": place.id,
        "name": place.name,
        "root_id": root_id,
        "blueprint_revision": int((blueprint or {}).get("revision") or (blueprint or {}).get("rev") or 0),
        "geometry": geometry,
    }


def _context_parts(ctx: Any) -> tuple[Any, Any, Any]:
    return ctx.session, ctx.world, getattr(ctx, "campaign", None)


async def observe_area(
    ctx: Any,
    place_id: str,
    hero_ids: list[str] | tuple[str, ...] | set[str],
    inverse: list[dict[str, Any]] | None = None,
    *,
    explicit: bool = False,
) -> bool:
    """Записать снимок для присутствующих героев в текущей транзакции."""
    session, world, campaign = _context_parts(ctx)
    place = world.entities.get(place_id)
    if place is None or getattr(place, "kind", None) != "location":
        return False
    complex_state = (place.state or {}).get("complex") or {}
    root = world.entities.get(complex_state.get("root_id")) or place
    blueprint = (root.state or {}).get("blueprint")
    if not blueprint:
        return False
    for hero_id in hero_ids:
        hero = world.characters.get(hero_id)
        if hero is None or (not explicit and hero.location_id != place_id):
            continue
        status = getattr(hero, "status", None)
        if status is not None and status not in {"approved", "active"}:
            continue
        row = await session.get(MapMemory, (hero_id, place_id))
        passages = frozenset()
        if row:
            passages = frozenset(
                (str(item.get("root_id")), str(item.get("passage_ref")))
                for item in (row.discovered_passages or [])
                if isinstance(item, dict) and item.get("root_id") and item.get("passage_ref")
            )
        snapshot = static_snapshot(
            place,
            root,
            blueprint,
            world.entities,
            discovered_passages=passages,
            revealed=frozenset(world.revealed.get(hero_id, set())),
        )
        if snapshot is None:
            continue
        before = None
        if row is None:
            row = MapMemory(character_id=hero_id, entity_id=place_id, snapshot=snapshot, revision=1)
            session.add(row)
        else:
            before = copy.deepcopy(row.snapshot)
            if row.snapshot == snapshot:
                continue
            row.snapshot = snapshot
            row.revision = int(row.revision or 0) + 1
        if inverse is not None:
            inverse.append({"table": "map_memories", "op": "restore", "id": [hero_id, place_id], "before": before})
        world.map_known.setdefault(hero_id, set()).add(place_id)
    return True


async def observe_present(ctx: Any, inverse: list[dict[str, Any]] | None = None, *, explicit: bool = False) -> bool:
    _, world, _ = _context_parts(ctx)
    location = world.scene.location_id
    heroes = [hero.id for hero in world.characters.values() if hero.location_id == location]
    return await observe_area(ctx, location, heroes, inverse, explicit=explicit) if location else False


async def known_passages(session: Any, hero_id: str, place_id: str) -> frozenset[tuple[str, str]]:
    row = await session.get(MapMemory, (hero_id, place_id))
    if row is None:
        return frozenset()
    return frozenset(
        (str(item["root_id"]), str(item["passage_ref"]))
        for item in (row.discovered_passages or [])
        if isinstance(item, dict) and item.get("root_id") and item.get("passage_ref")
    )


async def opened_areas(session: Any, hero_id: str) -> frozenset[str]:
    rows = await session.scalars(
        select(MapMemory.entity_id).where(MapMemory.character_id == hero_id, MapMemory.snapshot.is_not(None))
    )
    return frozenset(rows.all())


async def discover_passage(
    ctx: Any,
    root_id: str,
    passage_ref: str,
    hero_ids: list[str] | tuple[str, ...] | set[str],
    inverse: list[dict[str, Any]] | None = None,
) -> None:
    session, world, _ = _context_parts(ctx)
    for hero_id in hero_ids:
        rows = await session.scalars(
            select(MapMemory).where(MapMemory.character_id == hero_id, MapMemory.entity_id.in_(list(world.entities)))
        )
        memories = rows.all()
        row = next((item for item in memories if item.snapshot and item.snapshot.get("root_id") == root_id), None)
        if row is None:
            continue
        grants = list(row.discovered_passages or [])
        grant = {"root_id": root_id, "passage_ref": passage_ref}
        if grant not in grants:
            if inverse is not None:
                inverse.append(
                    {
                        "table": "map_memories",
                        "op": "restore",
                        "id": [hero_id, row.entity_id],
                        "before": copy.deepcopy(grants),
                    }
                )
            grants.append(grant)
            row.discovered_passages = grants
