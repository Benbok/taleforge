"""Explicit map regeneration for one author location.

The new map is prepared as a separate candidate root. Only when every phase of the candidate is ready is it
swapped in atomically: NPCs and key items move to their new homes, derived objects of the old map are removed,
the plot and geography point at the candidate. A failed candidate is removed and the old map stays as it was.
Ordinary games never use this path: their one-time preparation semantics are unchanged.
"""

import copy
import logging

from sqlalchemy import select, update

from app.core.authoring.materialization import _settle, _with_context, bind_geography
from app.core.layout import plan as layout_plan
from app.core.layout import store as layout_store
from app.core.world_generation import storage
from app.db.models import AuthorProject, CampaignSecret, Entity, PlotAnchorBinding, WorldGenerationState
from app.rules.dice import Dice

log = logging.getLogger(__name__)
WGS = WorldGenerationState
MAP_RESULTS = ("layout", "geometry", "placement")


class RegenerationError(Exception):
    def __init__(self, code: str, ref: str = ""):
        super().__init__(f"{code}: {ref}")
        self.code = code
        self.ref = ref


def _subtree(entities: dict[str, Entity], root_id: str) -> set[str]:
    """Root, its areas and everything located inside them (recursively)."""
    root = entities.get(root_id)
    found = {root_id, *layout_store.area_ids(root).values()} if root is not None else {root_id}
    found |= {e.id for e in entities.values() if (layout_store.complex_of(e) or {}).get("root_id") == root_id}
    changed = True
    while changed:
        inner = {e.id for e in entities.values() if e.location_id in found and e.id not in found}
        changed = bool(inner)
        found |= inner
    return found


def stale_refs_for(plan: dict, location_ref: str) -> set[str]:
    refs = {f"{kind}:{location_ref}" for kind in MAP_RESULTS}
    for route in plan.get("routes") or []:
        ends = (str(route.get("from", "")).split("/")[0], str(route.get("to", "")).split("/")[0])
        if location_ref in ends:
            refs.add(f"route_port:{route['ref']}")
    return refs


async def _reserve_candidate(ctx, location_ref: str) -> tuple[str, str, list[str]]:
    sketch = next((x for x in (ctx.world.plot or {}).get("locations") or [] if x["id"] == location_ref), None)
    if sketch is None or not sketch.get("entity_id") or sketch["entity_id"] not in ctx.world.entities:
        raise RegenerationError("location_not_materialized", location_ref)
    old = ctx.world.entities[sketch["entity_id"]]
    old_set = _subtree(ctx.world.entities, old.id)
    state = {k: v for k, v in (old.state or {}).items() if k in ("plot_id", "dc")}
    candidate = Entity(
        campaign_id=ctx.campaign.id,
        kind="location",
        name=sketch.get("name") or old.name,
        template_id=old.template_id,
        description=old.description,
        state={**state, "candidate_for": old.id},
    )
    ctx.session.add(candidate)
    await ctx.session.flush()
    ctx.world.entities[candidate.id] = candidate
    # Reserved plot anchors of the old place are offered to the candidate's mandate; reverted on failure.
    moved = list(
        await ctx.session.scalars(
            select(PlotAnchorBinding.id).where(
                PlotAnchorBinding.campaign_id == ctx.campaign.id,
                PlotAnchorBinding.state == "reserved",
                PlotAnchorBinding.target_location_id.in_(old_set),
            )
        )
    )
    if moved:
        await ctx.session.execute(
            update(PlotAnchorBinding).where(PlotAnchorBinding.id.in_(moved)).values(target_location_id=candidate.id)
        )
    row = await layout_plan.reserve_from_plan(ctx, candidate, sketch, [])
    if row is None:
        raise RegenerationError("not_eligible", location_ref)
    storage.activate(row)
    return candidate.id, old.id, moved


async def _discard(maker, campaign_id: str, candidate_id: str, old_id: str, moved: list[str]) -> None:
    async with maker() as s:
        entities = {e.id: e for e in await s.scalars(select(Entity).where(Entity.campaign_id == campaign_id))}
        for entity_id in _subtree(entities, candidate_id):
            await s.delete(entities[entity_id])
        if moved:
            await s.execute(
                update(PlotAnchorBinding).where(PlotAnchorBinding.id.in_(moved)).values(target_location_id=old_id)
            )
        await s.commit()


async def regenerate_location(maker, project_id: str, location_ref: str, preparer, dice_factory=Dice) -> dict:
    async with maker() as s:
        campaign_id = (await s.get(AuthorProject, project_id)).workspace_campaign_id

    async def reserve(ctx):
        return await _reserve_candidate(ctx, location_ref)

    candidate_id, old_id, moved = await _with_context(maker, campaign_id, dice_factory, reserve)
    await _settle(maker, campaign_id, preparer)

    async with maker() as s:
        entities = {e.id: e for e in await s.scalars(select(Entity).where(Entity.campaign_id == campaign_id))}
        fresh = _subtree(entities, candidate_id)
        rows = list(await s.scalars(select(WGS).where(WGS.campaign_id == campaign_id, WGS.target_entity_id.in_(fresh))))
    bad = [r.last_error or r.status for r in rows if r.status != "ready"]
    if not rows or bad:
        await _discard(maker, campaign_id, candidate_id, old_id, moved)
        return {"status": "blocked", "location_ref": location_ref, "reasons": bad or ["no_layout"]}

    await _swap(maker, project_id, campaign_id, location_ref, candidate_id, old_id)
    await bind_geography(maker, campaign_id)
    return {"status": "ready", "location_ref": location_ref, "entity_id": candidate_id}


async def _swap(maker, project_id: str, campaign_id: str, location_ref: str, candidate_id: str, old_id: str) -> None:
    async with maker() as s:
        project = await s.get(AuthorProject, project_id)
        secret = await s.get(CampaignSecret, campaign_id)
        plan = copy.deepcopy(secret.plot or {})
        entities = {e.id: e for e in await s.scalars(select(Entity).where(Entity.campaign_id == campaign_id))}
        candidate = entities[candidate_id]
        old_set = _subtree(entities, old_id)
        npc_refs = {n["id"] for n in plan.get("npcs") or []}
        keep = {
            e.id
            for e in entities.values()
            if e.id in old_set and ((e.state or {}).get("plot_id") in npc_refs or (e.state or {}).get("item_ref"))
        }
        new_areas = layout_store.area_ids(candidate)
        for entity_id in keep:  # authored inhabitants and key items survive the swap at their new places
            entity = entities[entity_id]
            st = entity.state or {}
            if st.get("item_ref"):
                item = next((i for i in plan.get("items") or [] if i.get("ref") == st["item_ref"]), {})
                area_ref = ((item.get("placement") or {}).get("area_ref")) or ""
                entity.location_id = new_areas.get(area_ref, candidate_id)
            else:
                entity.location_id = layout_store.home_of(entities, candidate_id, f"npc:{st['plot_id']}")
        for entity_id in old_set - keep:
            await s.delete(entities[entity_id])
        candidate.state = {k: v for k, v in (candidate.state or {}).items() if k != "candidate_for"}
        for loc in plan.get("locations") or []:
            if loc["id"] == location_ref:
                loc["entity_id"] = candidate_id
        secret.plot = plan
        stale = set((project.dependencies or {}).get("stale") or []) - stale_refs_for(plan, location_ref)
        project.dependencies = {**(project.dependencies or {}), "stale": sorted(stale)}
        await s.commit()
