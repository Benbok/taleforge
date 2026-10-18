"""What a draft edit invalidates. Derived from the plan, never from free-form text."""

from app.core.authoring.contracts import (
    DraftPatch,
    EditMap,
    RemoveObject,
    ResultRef,
    SetLore,
    SetPlacement,
    UpdateItem,
    UpsertRoute,
)

KINDS = ("locations", "npcs", "antagonists")
MAP_RESULTS = ("layout", "geometry", "placement")


def _routes_of(plan: dict, location_ref: str) -> list[str]:
    return [
        r["ref"]
        for r in plan.get("routes") or []
        if location_ref in (str(r.get("from", "")).split("/")[0], str(r.get("to", "")).split("/")[0])
    ]


def users_of(plan: dict, ref: str) -> tuple[ResultRef, ...]:
    """Objects that still point at ``ref`` (a location, NPC or item): they block its removal."""
    found: list[ResultRef] = []
    for npc in plan.get("npcs") or []:
        if npc.get("location_id") == ref:
            found.append(ResultRef(kind="npc", ref=npc["id"]))
    for loc in plan.get("locations") or []:
        if ref in ((loc.get("spatial") or {}).get("links") or []):
            found.append(ResultRef(kind="location", ref=loc["id"]))
    for route in _routes_of(plan, ref):
        found.append(ResultRef(kind="route", ref=route))
    for place in plan.get("placements") or []:
        if place.get("location_ref") == ref or place.get("ref") == ref:
            found.append(ResultRef(kind="placement", ref=place["ref"]))
    for item in plan.get("items") or []:
        if (item.get("placement") or {}).get("location_ref") == ref:
            found.append(ResultRef(kind="item", ref=item["ref"]))
    return tuple(found)


def affected_results(patch: DraftPatch, plan: dict) -> tuple[ResultRef, ...]:
    """Results that become stale. A name or text change touches nothing: maps stay valid."""
    out: dict[tuple[str, str], ResultRef] = {}

    def add(kind: str, ref: str) -> None:
        out[(kind, ref)] = ResultRef(kind=kind, ref=ref)

    for op in patch.operations:
        if isinstance(op, SetLore):
            add("stage", "plot")  # lore feeds the plot digest; downstream stages follow from it
        elif isinstance(op, EditMap):
            for kind in MAP_RESULTS:
                add(kind, op.location_ref)
            for route in _routes_of(plan, op.location_ref):
                add("route_port", route)
        elif isinstance(op, SetPlacement):
            add("placement", op.location_ref)
        elif isinstance(op, UpsertRoute):
            add("route_port", op.ref)
        elif isinstance(op, UpdateItem) and "template_id" in op.fields:
            add("placement", op.ref)
        elif isinstance(op, RemoveObject):
            for route in _routes_of(plan, op.ref):
                add("route_port", route)
    return tuple(out.values())
