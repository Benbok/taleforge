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
from app.db.models import Character, MapMemory

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
        ref = original.get("passage_ref")
        if original.get("hidden") and ref and (root_id, str(ref)) not in discovered_passages:
            continue
        item = {
            key: copy.deepcopy(value)
            for key, value in original.items()
            if key in {"name", "side", "at", "kind", "state", "width", "cells", "passage_ref"}
        }
        if ref and (root_id, str(ref)) not in discovered_passages:
            item.pop("to", None)
            item.pop("beyond", None)
            item.pop("passage_ref", None)
        exits.append(item)
    result["exits"] = exits
    features: list[dict[str, Any]] = []
    for original in raw.get("features") or []:
        if original.get("entity_id") or original.get("hidden"):
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
    secrets = {p["passage_ref"] for p in (blueprint or {}).get("passages", []) if p.get("hidden")}
    discovered_passages = discovered_passages | frozenset(
        (root_id, p["passage_ref"]) for p in (blueprint or {}).get("passages", []) if not p.get("hidden")
    )
    raw = {
        **raw,
        "exits": [
            x
            for x in raw.get("exits", [])
            if x.get("passage_ref") not in secrets or (root_id, x.get("passage_ref")) in discovered_passages
        ],
    }
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
        if hero is None or (not explicit and world.place_of(hero) != place_id):
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
        key = [hero_id, place_id]
        if row is None:
            row = MapMemory(character_id=hero_id, entity_id=place_id, snapshot=snapshot, revision=1)
            session.add(row)
            if inverse is not None:
                inverse.append({"table": "map_memories", "op": "delete", "id": key})
        else:
            if row.snapshot == snapshot:
                continue
            if inverse is not None:
                inverse += [
                    {"table": "map_memories", "id": key, "field": "snapshot", "before": copy.deepcopy(row.snapshot)},
                    {"table": "map_memories", "id": key, "field": "revision", "before": row.revision},
                ]
            row.snapshot = snapshot
            row.revision = int(row.revision or 0) + 1
        world.map_known.setdefault(hero_id, set()).add(place_id)
    return True


async def observe_present(ctx: Any, inverse: list[dict[str, Any]] | None = None, *, explicit: bool = False) -> bool:
    _, world, _ = _context_parts(ctx)
    location = world.scene.location_id
    heroes = [hero.id for hero in world.characters.values() if world.place_of(hero) == location]
    return await observe_area(ctx, location, heroes, inverse, explicit=explicit) if location else False


async def known_passages(session: Any, hero_id: str, place_id: str) -> frozenset[tuple[str, str]]:
    rows = await session.scalars(select(MapMemory).where(MapMemory.character_id == hero_id))
    return frozenset(
        (str(item["root_id"]), str(item["passage_ref"]))
        for row in rows
        for item in (row.discovered_passages or [])
        if isinstance(item, dict) and item.get("root_id") and item.get("passage_ref")
    )


async def known_passages_campaign(session: Any, campaign_id: str) -> frozenset[tuple[str, str]]:
    """Return passage discoveries shared by every hero in a campaign."""
    rows = await session.scalars(
        select(MapMemory)
        .join(Character, Character.id == MapMemory.character_id)
        .where(Character.campaign_id == campaign_id)
    )
    return frozenset(
        (str(item["root_id"]), str(item["passage_ref"]))
        for row in rows
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
        hero = world.characters.get(hero_id)
        if hero is None:
            continue
        rows = await session.scalars(
            select(MapMemory).where(MapMemory.character_id == hero_id, MapMemory.entity_id.in_(list(world.entities)))
        )
        memories = rows.all()
        # открытие хранится в любой строке героя: known_passages читает их все
        row = next((item for item in memories if item.snapshot and item.snapshot.get("root_id") == root_id), None)
        if row is None and memories:
            row = memories[0]
        grant = {"root_id": root_id, "passage_ref": passage_ref}
        if row is None:
            if hero.location_id is None:
                continue
            session.add(
                MapMemory(
                    character_id=hero_id,
                    entity_id=hero.location_id,
                    snapshot=None,
                    discovered_passages=[grant],
                    revision=0,
                )
            )
            if inverse is not None:
                inverse.append({"table": "map_memories", "op": "delete", "id": [hero_id, hero.location_id]})
            continue
        grants = list(row.discovered_passages or [])
        if grant in grants:
            continue
        if inverse is not None:
            inverse.append(
                {
                    "table": "map_memories",
                    "id": [hero_id, row.entity_id],
                    "field": "discovered_passages",
                    "before": copy.deepcopy(grants),
                }
            )
        row.discovered_passages = [*grants, grant]
