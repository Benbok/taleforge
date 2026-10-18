"""Materialize every planned place and NPC of an author world, without moving anyone.

Reuses the ``develop`` tool with ``here=False`` (no scene change, no party) and the existing
world-generation phases for layouts, geometry and container contents.
"""

import logging

from sqlalchemy import select

from app.core import plot
from app.core.authoring.contracts import AreaStatus, MaterializationReceipt, MaterializationReport
from app.core.layout import store as layout_store
from app.core.world_generation import storage
from app.db.models import AuthorProject, Campaign, Entity, WorldGenerationState
from app.rules.dice import Dice
from app.tools.registry import execute
from app.tools.runtime import flush_outbox, open_context

log = logging.getLogger(__name__)
WGS = WorldGenerationState
ROUNDS = 6  # layout -> geometry -> contents settle in a few rounds; a stuck row stays visible as pending


class MaterializationError(Exception):
    def __init__(self, code: str, ref: str):
        super().__init__(f"{code}: {ref}")
        self.code = code
        self.ref = ref


def _sketch(ctx, key: str, ref: str) -> dict:
    found = next((x for x in (ctx.world.plot or {}).get(key) or [] if x.get("id") == ref), None)
    if found is None:
        raise MaterializationError("unknown_sketch", ref)
    return found


async def _develop(ctx, sketch: dict, details: str) -> dict:
    out = await execute(ctx, "develop", {"sketch_id": sketch["id"], "details": details, "here": False})
    if not out.get("ok"):
        raise MaterializationError("develop_failed", sketch["id"])
    return out["result"]


async def ensure_location(ctx, node_ref: str) -> MaterializationReceipt:
    """Idempotent: an already developed place returns its entity; heroes and scene are never touched."""
    sketch = _sketch(ctx, "locations", node_ref)
    existing = sketch.get("entity_id")
    if sketch.get("status") != "sketch" and existing and existing in ctx.world.entities:
        row = await storage.find(ctx.session, ctx.campaign.id, existing, "location_layout")
        return MaterializationReceipt(
            ref=node_ref, entity_id=existing, created=False, layout_ref=row.id if row else None
        )
    result = await _develop(ctx, sketch, sketch.get("mood") or "авторская подготовка")
    layout = (result.get("layout") or {}).get("operation_ref")
    return MaterializationReceipt(ref=node_ref, entity_id=result["entity_id"], created=True, layout_ref=layout)


async def ensure_actor(ctx, plot_ref: str) -> str:
    """Create the NPC at its home inside the already prepared place; never in the current scene."""
    sketch = _sketch(ctx, "npcs", plot_ref)
    existing = sketch.get("entity_id")
    if sketch.get("status") != "sketch" and existing and existing in ctx.world.entities:
        return existing
    home_place = plot.sketch_entity(ctx.world.plot, sketch.get("location_id"))
    if home_place is None or home_place not in ctx.world.entities:
        raise MaterializationError("home_not_materialized", plot_ref)  # NPC without a real home is not placed
    result = await _develop(ctx, sketch, sketch.get("look") or "авторская подготовка")
    return result["entity_id"]


def holder_of(ctx, ref: str):
    """A container_ref names an authored container item or an NPC who carries the item."""
    found = next((e for e in ctx.world.entities.values() if (e.state or {}).get("item_ref") == ref), None)
    if found is not None and ((found.state or {}).get("world_object") or {}).get("role") == "container":
        return found
    npc = next((x for x in (ctx.world.plot or {}).get("npcs") or [] if x.get("id") == ref), None)
    return ctx.world.entities.get((npc or {}).get("entity_id") or "")


async def ensure_item(ctx, item: dict) -> str:
    """Put a key item into its concrete area, an authored container or an NPC's hands.

    An item that exists only in text is not prepared. A container item is created empty and holds others."""
    from app.tools.master.items import _put_in_scene

    ref = item["ref"]
    existing = next((e for e in ctx.world.entities.values() if (e.state or {}).get("item_ref") == ref), None)
    if existing is not None:
        return existing.id
    placement = item.get("placement") or next(
        (p for p in (ctx.world.plot or {}).get("placements") or [] if p.get("ref") == ref), None
    )
    if not placement:
        raise MaterializationError("item_not_placed", ref)
    holder = None
    if placement.get("container_ref"):
        holder = holder_of(ctx, placement["container_ref"])
        if holder is None:
            raise MaterializationError("container_missing", ref)
        area_id = holder.location_id
    else:
        location = next(
            (x for x in (ctx.world.plot or {}).get("locations") or [] if x["id"] == placement["location_ref"]), None
        )
        root = ctx.world.entities.get((location or {}).get("entity_id") or "")
        if root is None:
            raise MaterializationError("home_not_materialized", ref)
        area_id = (
            layout_store.area_ids(root).get(placement.get("area_ref") or "", root.id)
            if placement.get("area_ref")
            else root.id
        )
    if area_id not in ctx.world.entities:
        raise MaterializationError("unresolved_port", ref)
    if item.get("container"):
        # same shape as the create_container tool; the tool itself only accepts places the scene can see
        from app.tools.master.items import _container_state

        entity = Entity(
            campaign_id=ctx.campaign.id,
            kind="object",
            name=item.get("name") or ref,
            description=item.get("description") or "",
            location_id=area_id,
            zone="near",
            state={"visual_key": "item:chest", "world_object": _container_state()},
        )
        ctx.session.add(entity)
        await ctx.session.flush()
        ctx.world.entities[entity.id] = entity
        await ctx.record(
            "create_container", target_id=entity.id, payload={"container_id": entity.id, "name": entity.name}
        )
    else:
        if ctx.world.catalog.find(item["template_id"], "item_template") is None:
            raise MaterializationError("unknown_template", ref)
        entity, _inverse = await _put_in_scene(
            ctx,
            item["template_id"],
            item.get("name") or None,
            1,
            "near",
            place=area_id,
            container_id=holder.id if holder is not None else None,
            force_new=True,
        )
    entity.state = {**(entity.state or {}), "item_ref": ref}
    return entity.id


async def _with_context(maker, campaign_id: str, dice_factory, body):
    async with maker() as s:
        campaign = await s.get(Campaign, campaign_id)
        ctx = await open_context(s, campaign, dice_factory(), turn_id="author_prepare", seat_id=None)
        out = await body(ctx)
        await flush_outbox(s, ctx)
        await s.commit()
        return out


async def _settle(maker, campaign_id: str, preparer) -> None:
    """Activate and run every not-yet-requested phase (layout, geometry, container contents) of the world."""
    for _ in range(ROUNDS):
        async with maker() as s:
            rows = list(
                await s.scalars(
                    select(WGS).where(WGS.campaign_id == campaign_id, WGS.status.in_(("unprepared", "preparing")))
                )
            )
            for row in rows:
                await storage.activate_cas(s, row)
            await s.commit()
            refs = [r.id for r in rows]
        if not refs:
            return
        for ref in refs:
            await preparer.prepare(maker, campaign_id, ref)


async def prepare_world(maker, project_id: str, preparer, dice_factory=Dice) -> MaterializationReport:
    async with maker() as s:
        campaign_id = (await s.get(AuthorProject, project_id)).workspace_campaign_id
    blocked: dict[str, str] = {}

    async def places(ctx):
        for loc in list((ctx.world.plot or {}).get("locations") or []):
            try:
                await ensure_location(ctx, loc["id"])
            except MaterializationError as exc:
                blocked[loc["id"]] = exc.code

    await _with_context(maker, campaign_id, dice_factory, places)
    await _settle(maker, campaign_id, preparer)

    async def actors(ctx):
        for npc in list((ctx.world.plot or {}).get("npcs") or []):
            try:
                await ensure_actor(ctx, npc["id"])
            except MaterializationError as exc:
                blocked[npc["id"]] = exc.code

    await _with_context(maker, campaign_id, dice_factory, actors)
    await _with_context(maker, campaign_id, dice_factory, place_anchors)

    async def items(ctx):
        items_ = list((ctx.world.plot or {}).get("items") or [])
        # containers first, so that items placed inside them find their holder
        for item in sorted(items_, key=lambda x: not x.get("container")):
            try:
                await ensure_item(ctx, item)
            except MaterializationError as exc:
                blocked[item["ref"]] = exc.code

    await _with_context(maker, campaign_id, dice_factory, items)
    await bind_geography(maker, campaign_id)
    return await report(maker, campaign_id, blocked)


async def place_anchors(ctx) -> list[str]:
    """Plot clue carriers are put into their prepared areas now, not when heroes first walk in."""
    from app.core import plot_anchors

    made: list[str] = []
    for loc in (ctx.world.plot or {}).get("locations") or []:
        root = ctx.world.entities.get(loc.get("entity_id") or "")
        if root is None:
            continue
        for target_id in [*layout_store.area_ids(root).values(), root.id]:
            target = ctx.world.entities.get(target_id)
            if target is None:
                continue
            phase = "location_geometry" if layout_store.complex_of(target) else "location_layout"
            row = await storage.find(ctx.session, ctx.campaign.id, target.id, phase)
            made += await plot_anchors.materialize_late(ctx, target, row.id if row else target.id)
    return made


async def bind_geography(maker, campaign_id: str) -> None:
    """Record entity ids on geography nodes and store each route port as concrete cells of its area."""
    from app.core.geography import ports
    from app.core.geography.compiler import compile_plan
    from app.core.geography.storage import sync_geography
    from app.db.models import CampaignSecret

    async with maker() as s:
        secret = await s.get(CampaignSecret, campaign_id)
        plan = (secret.plot if secret else None) or {}
        draft = compile_plan(plan)
        entity_by_ref = {x["id"]: x["entity_id"] for x in plan.get("locations") or [] if x.get("entity_id")}
        view = await sync_geography(s, campaign_id, draft, entity_by_ref)
        entities = {e.id: e for e in await s.scalars(select(Entity).where(Entity.campaign_id == campaign_id))}
        ids = {n.ref: n.entity_id for n in view.nodes if n.entity_id}
        names = {n.ref: n.name for n in view.nodes}
        for link in view.links:
            try:
                ends = [ports.resolve_port(entities, ids, end) for end in (link.source, link.target)]
            except Exception:  # noqa: BLE001 — an unresolved port is reported by validation, not guessed here
                continue
            for i, port in enumerate(ends):
                other = ends[1 - i]
                area = entities[port.area_id]
                sketch = (area.state or {}).get("sketch")
                cells = ports.place_port_cells(sketch) if sketch else []
                held = dict((area.state or {}).get("route_ports") or {})
                held[link.ref] = {"cells": [list(c) for c in cells]}
                state = {**(area.state or {}), "route_ports": held}
                if sketch and cells and (i == 0 or link.bidirectional):
                    exits = [x for x in sketch.get("exits") or [] if x.get("route_ref") != link.ref]
                    label = names.get(other.node_ref, other.node_ref)
                    exit_ = ports.port_exit(sketch, cells, link.ref, label, other.area_id, link.hidden)
                    state["sketch"] = {**sketch, "exits": [*exits, exit_]}
                area.state = state
        await s.commit()


async def report(maker, campaign_id: str, blocked: dict[str, str] | None = None) -> MaterializationReport:
    """Separates "not requested" from "ready": listing objects in the plan does not count as preparation."""
    blocked = blocked or {}
    async with maker() as s:
        from app.db.models import CampaignSecret

        secret = await s.get(CampaignSecret, campaign_id)
        plan = (secret.plot if secret else None) or {}
        entities = {e.id: e for e in await s.scalars(select(Entity).where(Entity.campaign_id == campaign_id))}
        rows = list(await s.scalars(select(WGS).where(WGS.campaign_id == campaign_id)))
    by_root: dict[str, list[WorldGenerationState]] = {}
    for row in rows:
        target = entities.get(row.target_entity_id)
        root = (layout_store.complex_of(target) or {}).get("root_id") if target is not None else None
        by_root.setdefault(root or row.target_entity_id, []).append(row)

    def status_of(ref: str, entity_id: str | None, group: list) -> AreaStatus:
        if ref in blocked:
            return AreaStatus(ref=ref, entity_id=entity_id, status="blocked", reasons=(blocked[ref],))
        if not entity_id or entity_id not in entities:
            return AreaStatus(ref=ref, status="not_requested")
        bad = [r.last_error or r.status for r in group if r.status == "blocked"]
        if bad:
            return AreaStatus(ref=ref, entity_id=entity_id, status="blocked", reasons=tuple(bad))
        if any(r.status != "ready" for r in group):
            return AreaStatus(ref=ref, entity_id=entity_id, status="preparing")
        return AreaStatus(ref=ref, entity_id=entity_id, status="ready")

    locations = tuple(
        status_of(x["id"], x.get("entity_id"), by_root.get(x.get("entity_id") or "", []))
        for x in plan.get("locations") or []
    )
    actors = tuple(status_of(x["id"], x.get("entity_id"), []) for x in plan.get("npcs") or [])
    item_ids = {(e.state or {}).get("item_ref"): e.id for e in entities.values() if (e.state or {}).get("item_ref")}
    items = tuple(status_of(x["ref"], item_ids.get(x["ref"]), []) for x in plan.get("items") or [])
    return MaterializationReport(
        locations=locations,
        actors=actors,
        items=items,
        pending_rows=sum(r.status in ("unprepared", "preparing") for r in rows),
        blocked_rows=sum(r.status == "blocked" for r in rows),
    )
