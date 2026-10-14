"""NPC companions: the relationship lives in ``Entity.state``.

This module deliberately keeps the public projection small.  Plot metadata,
the reason for joining, and the owner's identity are server-side state and are
never returned by :func:`public_companion`.
"""

from __future__ import annotations

import copy
from typing import Any


def companion_record(entity: Any) -> dict[str, str] | None:
    """Return a valid companion record or ``None`` for an unlinked entity."""

    record = (getattr(entity, "state", None) or {}).get("companion")
    if not isinstance(record, dict):
        return None
    owner = record.get("of")
    if not isinstance(owner, str) or not owner:
        return None
    return {
        key: value
        for key, value in record.items()
        if key in {"of", "since_event", "reason"} and isinstance(value, str)
    }


def companion_is_active(entity: Any) -> bool:
    record = companion_record(entity)
    state = getattr(entity, "state", None) or {}
    return bool(
        record
        and not state.get("dead")
        and not state.get("fled")
        and state.get("attitude", "hostile") != "hostile"
    )


def companions_for_hero(world: Any, hero_id: str, *, place: str | None = None) -> list[Any]:
    """Find active companions owned by ``hero_id`` in stable world order."""

    out = []
    for entity in world.entities.values():
        if getattr(entity, "kind", None) != "creature":
            continue
        record = companion_record(entity)
        if not record or record.get("of") != hero_id or not companion_is_active(entity):
            continue
        if place is not None and getattr(entity, "location_id", None) != place:
            continue
        out.append(entity)
    return out


def public_companion(entity: Any) -> dict[str, Any]:
    """Build the table-visible companion row without relationship secrets."""

    state = getattr(entity, "state", None) or {}
    hp = state.get("hp")
    hp_max = state.get("hp_max")
    return {
        "id": entity.id,
        "name": entity.name,
        "hp": hp,
        "hp_max": hp_max,
        "down": bool(hp == 0 and not state.get("dead")),
        "dead": bool(state.get("dead")),
    }


def public_companions(world: Any, hero_id: str, *, place: str | None = None) -> list[dict[str, Any]]:
    return [public_companion(entity) for entity in companions_for_hero(world, hero_id, place=place)]


# Public name used by callers that describe the relationship from the hero's
# point of view.  Keep the implementation in one place so filtering rules do
# not diverge between projections and movement.
companions_of = companions_for_hero


def companion_inverse(entity: Any) -> dict[str, Any]:
    """Snapshot the fields that movement and relationship tools mutate."""

    return {
        "table": "entities",
        "id": entity.id,
        "field": "state",
        "before": copy.deepcopy(getattr(entity, "state", None)),
    }


def bring_companions(world: Any, heroes: list[Any], loc: Any, inverse: list[dict[str, Any]]) -> list[Any]:
    """Move companions that share a departing hero's place.

    The caller invokes this before changing hero locations.  A companion's
    exact combat geometry is local to the old scene, so a transition always
    places it near the group and clears those fields atomically with the move.
    """

    destination = loc.id
    moved: list[Any] = []
    seen: set[str] = set()
    scene_location = getattr(getattr(world, "scene", None), "location_id", None)
    for hero in heroes:
        source = getattr(hero, "location_id", None) or scene_location
        for entity in companions_for_hero(world, hero.id, place=source):
            if entity.id in seen:
                continue
            seen.add(entity.id)
            inverse.extend(
                [
                    companion_inverse(entity),
                    {"table": "entities", "id": entity.id, "field": "location_id", "before": entity.location_id},
                    {"table": "entities", "id": entity.id, "field": "zone", "before": entity.zone},
                ]
            )
            state = dict(entity.state or {})
            for key in ("cell", "bearing", "cover", "elevation"):
                state.pop(key, None)
            entity.state = state
            entity.location_id = destination
            entity.zone = "near"
            invalidate = getattr(world, "invalidate", None)
            if invalidate is not None:
                invalidate(entity.id)
            moved.append(entity)
    return moved
