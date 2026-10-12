"""Безопасная проекция открытой карты комплекса для одного зрителя."""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import map_memory
from app.core.layout import store
from app.db.models import Entity, MapMemory


def _area_meta(root: Entity, place: Entity) -> tuple[dict[str, Any], Any] | None:
    bp = store.blueprint_of(root)
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
    observed_at: Any = None,
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
        "observed_at": observed_at,
        "sketch": geometry,
        "disclosed_to": disclosed_to,
    }


async def location_plan(
    session: AsyncSession,
    viewer: Any,
    entities: dict[str, Entity],
    here_id: str | None,
) -> dict[str, Any] | None:
    """Собрать только текущий и персонально сохранённые участки комплекса."""
    here = entities.get(here_id or "")
    if here is None:
        return None
    complex_state = (here.state or {}).get("complex") or {}
    root_id = complex_state.get("root_id")
    root = entities.get(root_id or "")
    if root is None or store.blueprint_of(root) is None:
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
    current = map_memory.static_snapshot(
        here,
        root,
        (root.state or {}).get("blueprint"),
        entities,
        discovered_passages=frozenset(
            (root.id, str(exit.get("passage_ref")))
            for exit in ((here.state or {}).get("sketch") or {}).get("exits") or []
            if exit.get("passage_ref")
        ),
        revealed=frozenset(),
    )
    if current is None:
        return None
    areas: list[dict[str, Any]] = []
    meta = _area_meta(root, here)
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
        area_meta = _area_meta(root, place)
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
