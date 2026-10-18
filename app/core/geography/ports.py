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
