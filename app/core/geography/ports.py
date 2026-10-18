"""Resolve a route endpoint to the real area of a materialized location; never guess a neighbour."""

from app.core.geography.contracts import GeographyError, RouteEndpoint, RoutePort
from app.core.layout import store


def resolve_port(entities: dict, entity_ids: dict[str, str], endpoint: RouteEndpoint) -> RoutePort:
    """``entity_ids`` maps a geography node ref to its root Entity id.

    A complex's part resolves to that part's own area Entity, not to the root or the first entrance.
    A mismatched port raises instead of falling back to another part.
    """
    entity_id = entity_ids.get(endpoint.node_ref)
    place = entities.get(entity_id) if entity_id else None
    if place is None:
        raise GeographyError("port_not_materialized", endpoint.node_ref)
    if store.area_ids(place):
        if not endpoint.area_ref:
            raise GeographyError("port_area_required", endpoint.node_ref)
        area_id = store.area_ids(place).get(endpoint.area_ref)
        if not area_id or area_id not in entities:
            raise GeographyError("unresolved_port", f"{endpoint.node_ref}/{endpoint.area_ref}")
        return RoutePort(node_ref=endpoint.node_ref, area_ref=endpoint.area_ref, area_id=area_id)
    if endpoint.area_ref:
        raise GeographyError("unresolved_port", f"{endpoint.node_ref}/{endpoint.area_ref}")
    return RoutePort(node_ref=endpoint.node_ref, area_ref="", area_id=place.id)


def place_port_cells(sketch: dict) -> list[tuple[int, int]]:
    """Deterministic exit cell: the walkable cell nearest the area's border, reachable from its entrance."""
    from app.core import reach

    party = tuple(sketch.get("party") or ())
    if len(party) != 2:
        return []
    region = reach.walk_region(sketch, party)
    if not region:
        return []
    cols, rows = int(sketch["cols"]), int(sketch["rows"])

    def edge(cell):
        return min(cell[0], cell[1], cols - 1 - cell[0], rows - 1 - cell[1])

    return [min(region, key=lambda c: (edge(c), c[1], c[0]))]


def port_exit(sketch: dict, cells: list, route_ref: str, name: str, to_id: str | None, hidden: bool) -> dict:
    """The port projected onto the area sketch as a geographic exit at its nearest edge."""
    cols, rows = int(sketch["cols"]), int(sketch["rows"])
    x, y = cells[0]
    side, at = min(
        (("w", y, x), ("e", y, cols - 1 - x), ("n", x, y), ("s", x, rows - 1 - y)), key=lambda t: (t[2], t[0])
    )[:2]
    return {
        "name": name,
        "side": side,
        "at": at,
        "width": 1,
        "kind": "passage",
        "state": "open",
        "hidden": hidden,
        "to": to_id,
        "beyond": None,
        "passage_ref": None,
        "route_ref": route_ref,
        "cells": [list(c) for c in cells],
    }
