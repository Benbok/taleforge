"""Безопасная проекция открытой карты комплекса для одного зрителя."""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import map_memory
from app.core.layout import geometry, store
from app.db.models import Character, Entity, MapMemory


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


def _outline_snapshot(root, bp, area, *, root_id: str) -> dict[str, Any]:
    """Build a public, detail-free sketch for an undiscovered area."""
    raw = geometry.build_area(bp, area, root_id=root_id, ids={})
    # The outline is useful for orientation, but must not disclose furniture,
    # hidden details, or the exact internal passage network.
    raw["walls"] = []
    raw["features"] = []
    raw["exits"] = []
    raw.pop("blueprint", None)
    raw["party"] = [max(0, area.cols // 2), max(0, area.rows // 2)]
    return {"name": area.public_name, "geometry": raw}


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
    root_id = complex_state.get("root_id") or (
        here.id if isinstance((here.state or {}).get("blueprint"), dict) else None
    )
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
    if root_id:
        # Exploration is shared by the party. Keep the newest snapshot for a
        # location when more than one hero has observed it.
        q = (
            select(MapMemory)
            .join(Character, Character.id == MapMemory.character_id)
            .where(Character.campaign_id == root.campaign_id)
            .order_by(MapMemory.updated_at.desc(), MapMemory.character_id.asc())
        )
        all_rows = list((await session.scalars(q)).all())
        seen: set[str] = set()
        for row in all_rows:
            if row.snapshot is None:
                continue
            place = entities.get(row.entity_id)
            if place is None or ((place.state or {}).get("complex") or {}).get("root_id") != root.id:
                continue
            if row.entity_id not in seen:
                rows.append(row)
                seen.add(row.entity_id)
    by_id = {row.entity_id: row for row in rows}
    grants = await map_memory.known_passages(session, hero_id, here.id) if hero_id else frozenset()
    if root_id:
        grants |= frozenset(
            (str(item.get("root_id")), str(item.get("passage_ref")))
            for row in all_rows
            for item in (row.discovered_passages or [])
            if isinstance(item, dict) and item.get("root_id") and item.get("passage_ref")
        )
    permitted = frozenset(
        (root.id, p.passage_ref) for p in bp.passages if not p.hidden or (root.id, p.passage_ref) in grants
    )
    areas: list[dict[str, Any]] = []
    current = None
    if here.id != root.id:
        current = map_memory.static_snapshot(
            here, root, (root.state or {}).get("blueprint"), entities,
            discovered_passages=permitted if hero_id else frozenset((root.id, p.passage_ref) for p in bp.passages),
            revealed=frozenset(),
        )
        if current is None:
            return None
        current["geometry"]["exits"] = [
            x for x in current["geometry"].get("exits", [])
            if not x.get("passage_ref") or (root.id, x["passage_ref"]) in permitted or not hero_id
        ]
    ids = store.area_ids(root)
    for area in bp.areas:
        place = entities.get(ids.get(area.area_ref, ""))
        if place is None or (area.secret and place.id not in by_id and place.id != here.id):
            continue
        area_meta = _area_meta(bp, place)
        if place.id == here.id and current is not None:
            packet = _area_packet(
                place,
                current,
                status="here",
                revision=int((by_id.get(place.id).revision if by_id.get(place.id) else 0) or 0),
                meta=area_meta[0] if area_meta else None,
            )
        elif place.id in by_id:
            row = by_id[place.id]
            packet = _area_packet(
                place,
                row.snapshot,
                status="remembered",
                revision=row.revision,
                observed_at=row.updated_at,
                meta=area_meta[0] if area_meta else None,
            )
        else:
            packet = _area_packet(
                place,
                _outline_snapshot(root, bp, area, root_id=root.id),
                status="prepared",
                revision=0,
                meta=area_meta[0] if area_meta else None,
            )
        areas.append(packet)
    return {"root_id": root.id, "here_id": None if here.id == root.id else here.id, "areas": areas}
