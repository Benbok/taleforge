"""Deterministic readiness report for an author project. No LLM, no visits, no container opening, no movement."""

import hashlib
import json
from collections import deque

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import reach
from app.core.authoring.contracts import ValidationIssue, ValidationReport
from app.core.geography import ports
from app.core.geography.compiler import compile_plan
from app.core.geography.contracts import GeographyError, RouteEndpoint
from app.core.layout import store as layout_store
from app.db.models import AuthorJob, AuthorProject, CampaignSecret, Entity, WorldGenerationState

OPEN_JOBS = ("queued", "running", "blocked", "failed", "stale")
CLOSED_ROUTE_STATES = ("closed", "locked", "blocked")


def source_digest(plan: dict, setting: dict) -> str:
    body = json.dumps([plan, setting], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def _issue(code: str, ref: str | None = None, *related: str, message: str = "") -> ValidationIssue:
    return ValidationIssue(code=code, object_ref=ref, related_refs=tuple(related), message=message)


def _reach(links, start: str, *, conditions: bool) -> set[str]:
    """Nodes reachable from start. With ``conditions`` hidden/closed routes count as passable (conditional)."""
    adj: dict[str, set[str]] = {}
    for link in links:
        if not conditions and (link.hidden or link.constraints.get("state") in CLOSED_ROUTE_STATES):
            continue
        adj.setdefault(link.source.node_ref, set()).add(link.target.node_ref)
        if link.bidirectional:
            adj.setdefault(link.target.node_ref, set()).add(link.source.node_ref)
    seen, queue = {start}, deque([start])
    while queue:
        for nxt in adj.get(queue.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


async def validate_project(session: AsyncSession, project: AuthorProject) -> ValidationReport:
    cid = project.workspace_campaign_id
    secret = await session.get(CampaignSecret, cid)
    plan, setting = (secret.plot if secret else None) or {}, (secret.setting if secret else None) or {}
    entities = {e.id: e for e in await session.scalars(select(Entity).where(Entity.campaign_id == cid))}
    rows = list(await session.scalars(select(WorldGenerationState).where(WorldGenerationState.campaign_id == cid)))
    jobs = list(
        await session.scalars(
            select(AuthorJob).where(AuthorJob.project_id == project.id, AuthorJob.status.in_(OPEN_JOBS))
        )
    )
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    for stale in (project.dependencies or {}).get("stale") or []:
        errors.append(_issue("stale_result", stale))
    for job in jobs:
        errors.append(_issue("preparation_blocked", job.target_ref or job.stage, message=f"{job.stage}:{job.status}"))
    for row in rows:
        if row.status != "ready":
            errors.append(_issue("preparation_blocked", row.target_entity_id, message=f"{row.phase}:{row.status}"))

    covered_parts = total_parts = 0
    location_entity: dict[str, str] = {}
    for loc in plan.get("locations") or []:
        entity = entities.get(loc.get("entity_id") or "")
        if entity is None or entity.kind != "location":
            errors.append(_issue("missing_location", loc["id"]))
            continue
        location_entity[loc["id"]] = entity.id
        areas = layout_store.area_ids(entity)
        if not areas:
            total_parts += 1
            if (entity.state or {}).get("sketch"):
                covered_parts += 1
            else:
                errors.append(_issue("missing_geometry", loc["id"]))
            continue
        for area_ref, area_id in areas.items():
            total_parts += 1
            area = entities.get(area_id)
            if area is None or not (area.state or {}).get("sketch"):
                errors.append(_issue("missing_geometry", f"{loc['id']}/{area_ref}"))
            else:
                covered_parts += 1

    try:
        draft = compile_plan(plan)
    except GeographyError as exc:
        errors.append(_issue("unresolved_route", exc.refs[0] if exc.refs else None, *exc.refs[1:], message=exc.code))
        draft = None
    routes_checked = 0
    if draft is not None:
        ids = {n.ref: location_entity[n.ref] for n in draft.nodes if n.ref in location_entity}
        for link in draft.links:
            explicit = not link.ref.startswith("legacy:") or any(e.area_ref for e in (link.source, link.target))
            if not explicit:
                continue
            routes_checked += 1
            for end in (link.source, link.target):
                err = _check_port(entities, ids, end, link.ref)
                if err is not None:
                    errors.append(err)
        if draft.start_ref:
            start_ok = _reach(draft.links, draft.start_ref, conditions=False)
            conditional = _reach(draft.links, draft.start_ref, conditions=True)
            for loc in plan.get("locations") or []:
                if loc["id"] in start_ok:
                    continue
                if loc["id"] in conditional:  # intentionally gated: a condition, not a missing path
                    warnings.append(_issue("conditional_access", loc["id"]))
                elif loc.get("optional") is not True and len(draft.nodes) > 1:
                    errors.append(_issue("unreachable_location", loc["id"], draft.start_ref))

    actors = 0
    for npc in plan.get("npcs") or []:
        actors += 1
        if npc.get("appears_when"):  # no executable contract exists for custom spawn conditions
            errors.append(_issue("unsupported_reference", npc["id"], message="appears_when"))
        entity = entities.get(npc.get("entity_id") or "")
        home = entities.get(entity.location_id or "") if entity is not None else None
        if entity is None or home is None or home.kind != "location":
            errors.append(_issue("unplaced_actor", npc["id"]))

    items = 0
    for item in plan.get("items") or []:
        items += 1
        if not any((e.state or {}).get("item_ref") == item["ref"] for e in entities.values()):
            errors.append(_issue("missing_item", item["ref"]))

    return ValidationReport(
        source_revision=project.draft_revision,
        source_digest=source_digest(plan, setting),
        errors=tuple(errors),
        warnings=tuple(warnings),
        coverage={
            "locations": len(location_entity),
            "parts_total": total_parts,
            "parts_ready": covered_parts,
            "routes": routes_checked,
            "actors": actors,
            "items": items,
        },
    )


def _check_port(entities: dict, ids: dict, end: RouteEndpoint, route_ref: str) -> ValidationIssue | None:
    try:
        port = ports.resolve_port(entities, ids, end)
    except GeographyError as exc:
        return _issue("unresolved_route", route_ref, f"{end.node_ref}/{end.area_ref or ''}", message=exc.code)
    area = entities[port.area_id]
    sketch = (area.state or {}).get("sketch")
    held = ((area.state or {}).get("route_ports") or {}).get(route_ref) or {}
    cells = [tuple(c) for c in held.get("cells") or []]
    if sketch is None or not cells:
        return _issue("unreachable_port", route_ref, port.area_id, message="no port cells")
    party = tuple(sketch.get("party") or ())
    region = reach.walk_region(sketch, party) if len(party) == 2 else set()
    if any(c not in region for c in cells):  # a cell behind a wall or cut off from the entrance
        return _issue("unreachable_port", route_ref, port.area_id, message="cell not walkable from entrance")
    return None


async def store_report(session: AsyncSession, project: AuthorProject, report: ValidationReport) -> None:
    project.validation_report = report.model_dump(mode="json")
