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
    return await report(maker, campaign_id, blocked)


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
    return MaterializationReport(
        locations=locations,
        actors=actors,
        pending_rows=sum(r.status in ("unprepared", "preparing") for r in rows),
        blocked_rows=sum(r.status == "blocked" for r in rows),
    )
