"""Безопасная проекция открытой карты комплекса для одного зрителя."""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import map_memory
from app.core.layout import store
from app.db.models import Entity, MapMemory


def _area_meta(bp, place: Entity) -> tuple[dict[str, Any], Any] | None:
    if bp is None:
        return None
    ref = ((place.state or {}).get("complex") or {}).get("area_ref")
    area = bp.area(ref)
    return ({"offset": list(area.offset), "level": area.level}, area) if area is not None else None


def _area_packet(
    place: Entity,
    snapshot: dict[str, Any],
    *,
    status: str,
    revision: int,
    observed_at: datetime | None = None,
    disclosed_to: list[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    geometry = copy.deepcopy(snapshot.get("geometry") or {})
    return {
        "id": place.id,
        "name": snapshot.get("name") or place.name,
        "offset": list((meta or {}).get("offset") or [0, 0]),
        "level": int((meta or {}).get("level") or 0),
        "status": status,
        "revision": int(revision),
        # пакет уходит через send_json без pydantic-сериализации: время — строкой ISO
        "observed_at": observed_at.isoformat() if observed_at is not None else None,
        "sketch": geometry,
        "disclosed_to": disclosed_to,
    }


async def location_plan(
    session: AsyncSession,
    viewer: Any,
    entities: dict[str, Entity],
    here_id: str | None,
    blueprint_cache: dict | None = None,
) -> dict[str, Any] | None:
    """Собрать только текущий и персонально сохранённые участки комплекса."""
    here = entities.get(here_id or "")
    if here is None:
        return None
    complex_state = (here.state or {}).get("complex") or {}
    root_id = complex_state.get("root_id")
    root = entities.get(root_id or "")
    if root is None:
        return None
    cache = blueprint_cache if blueprint_cache is not None else {}
    if root.id not in cache:
        cache[root.id] = store.blueprint_of(root)
    bp = cache[root.id]
    if bp is None:
        return None
    hero_id = getattr(viewer, "id", None) or getattr(viewer, "hero_id", None)
    if hero_id is None and isinstance(viewer, str):
        hero_id = viewer
    rows = []
    if hero_id:
        rows = list(
            (
                await session.scalars(
                    select(MapMemory).where(MapMemory.character_id == hero_id, MapMemory.snapshot.is_not(None))
                )
            ).all()
        )
    by_id = {row.entity_id: row for row in rows}
    grants = await map_memory.known_passages(session, hero_id, here.id) if hero_id else frozenset()
    permitted = frozenset(
        (root.id, p.passage_ref) for p in bp.passages if not p.hidden or (root.id, p.passage_ref) in grants
    )
    current = map_memory.static_snapshot(
        here,
        root,
        (root.state or {}).get("blueprint"),
        entities,
        discovered_passages=permitted if hero_id else frozenset((root.id, p.passage_ref) for p in bp.passages),
        revealed=frozenset(),
    )
    if current is None:
        return None
    current["geometry"]["exits"] = [
        x
        for x in current["geometry"].get("exits", [])
        if not x.get("passage_ref") or (root.id, x["passage_ref"]) in permitted or not hero_id
    ]
    areas: list[dict[str, Any]] = []
    meta = _area_meta(bp, here)
    areas.append(
        _area_packet(
            here,
            current,
            status="here",
            revision=int((by_id.get(here.id).revision if by_id.get(here.id) else 0) or 0),
            meta=meta[0] if meta else None,
        )
    )
    for row in rows:
        if row.entity_id == here.id or not row.snapshot:
            continue
        place = entities.get(row.entity_id)
        if place is None:
            continue
        if ((place.state or {}).get("complex") or {}).get("root_id") != root.id:
            continue
        area_meta = _area_meta(bp, place)
        areas.append(
            _area_packet(
                place,
                row.snapshot,
                status="remembered",
                revision=row.revision,
                observed_at=row.updated_at,
                meta=area_meta[0] if area_meta else None,
            )
        )
    return {"root_id": root.id, "here_id": here.id, "areas": areas}
