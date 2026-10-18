"""Server-side route travel: resolves the route, checks the heroes and moves them atomically."""

from pydantic import BaseModel

from app.core import combat
from app.core.geography import ports
from app.core.geography.contracts import GeographyError, GeographyView, LinkDraft, RouteEndpoint
from app.core.world import PLAYABLE

CLOSED_STATES = ("closed", "locked", "blocked")


class TravelResult(BaseModel):
    moved: list[str] = []
    source_area_id: str | None = None
    destination_area_id: str | None = None
    route_id: str
    failure_code: str | None = None


def _fail(route_id: str, code: str, source: str | None = None) -> TravelResult:
    return TravelResult(route_id=route_id, failure_code=code, source_area_id=source)


def resolve_direction(
    entities: dict, view: GeographyView, link: LinkDraft, here_id: str
) -> tuple[RouteEndpoint, RouteEndpoint, str, str] | str:
    """(from, to, source_area_id, destination_area_id) for the area the heroes stand in, or a failure code."""
    entity_ids = {n.ref: n.entity_id for n in view.nodes if n.entity_id}
    try:
        a = ports.resolve_port(entities, entity_ids, link.source)
        b = ports.resolve_port(entities, entity_ids, link.target)
    except GeographyError:
        return "unresolved_route"
    if here_id == a.area_id:
        return link.source, link.target, a.area_id, b.area_id
    if here_id == b.area_id:
        return (link.target, link.source, b.area_id, a.area_id) if link.bidirectional else "one_way"
    return "not_at_port"  # a reverse stair or another room never stands in for the chosen route


async def travel_route(ctx, route_id: str, character_ids: list[str], action_ref: dict | None = None) -> TravelResult:
    """Moves the given heroes along an authored route. Any failure means no one moved; no fallback route is chosen."""
    from app.tools.master.places import _character, move_heroes

    view: GeographyView | None = getattr(ctx.world, "geography", None)
    link = next((x for x in (view.links if view else ()) if x.ref == route_id), None)
    if link is None:
        return _fail(route_id, "unknown_route")
    if link.hidden:
        return _fail(route_id, "route_hidden")
    if (link.constraints or {}).get("state") in CLOSED_STATES:
        return _fail(route_id, "route_closed")
    heroes = [_character(ctx, cid) for cid in character_ids]
    if not heroes or any(h.status not in PLAYABLE for h in heroes):
        return _fail(route_id, "hero_unavailable")
    if combat.in_combat(ctx):
        return _fail(route_id, "in_combat")
    scene_loc = ctx.world.scene.location_id
    starts = {h.location_id or scene_loc for h in heroes}
    if len(starts) != 1 or None in starts:
        return _fail(route_id, "split_party_mismatch")
    here_id = next(iter(starts))
    direction = resolve_direction(ctx.world.entities, view, link, here_id)
    if isinstance(direction, str):
        return _fail(route_id, direction, here_id)
    _src, _dst, source_id, dest_id = direction
    destination = ctx.world.entities.get(dest_id)
    held = ((destination.state or {}).get("route_ports") or {}).get(link.ref) if destination is not None else None
    if destination is None or not (held or {}).get("cells"):
        return _fail(route_id, "port_unavailable", source_id)
    inverse: list = []
    dice: list = []
    await move_heroes(ctx, heroes, destination, inverse, dice, connect=False)
    await ctx.record(
        "travel_route",
        target_id=destination.id,
        payload={
            "route_id": route_id,
            "characters": character_ids,
            "source_area_id": source_id,
            "destination_area_id": dest_id,
            "action_ref": action_ref,
        },
        dice=dice or None,
        inverse=inverse,
    )
    return TravelResult(
        moved=list(character_ids), source_area_id=source_id, destination_area_id=dest_id, route_id=route_id
    )
