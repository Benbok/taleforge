"""Stage handlers. Each returns a JSON-safe result; later stages register here as they are built."""

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select

from app.agents import architect
from app.core.authoring.lore import LoreError, generate_lore
from app.core.authoring.projects import author_write
from app.db.models import AuthorJob, AuthorProject, CampaignSecret


class StageError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class StageContext:
    svc: object
    project_id: str
    world_id: str
    job_id: str
    stage: str


Handler = Callable[[StageContext], Awaitable[dict]]

# Upper estimate reserved before a stage runs; real spend is read back from LlmCall.
ESTIMATE_USD = {"lore": 0.05, "plot": 0.40}


def output_digest(result: dict) -> str:
    return hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


async def lore_stage(ctx: StageContext) -> dict:
    try:
        lore = await generate_lore(ctx.svc, ctx.world_id, ctx.job_id)
    except LoreError as exc:
        raise StageError(exc.code) from exc
    return {"lore": lore}


async def plot_stage(ctx: StageContext) -> dict:
    # The plot reuses the architect; the author flow never prepares the voiced intro.
    version_id = await architect.generate(ctx.svc, ctx.world_id, prepare_intro=False, author_job_id=ctx.job_id)
    if version_id is None:
        raise StageError("plot_failed")
    removed = await clear_materialized_world(ctx.svc.maker, ctx.project_id, ctx.world_id)
    return {"plan_version_id": version_id, "cleared_entities": removed}


async def clear_materialized_world(maker, project_id: str, world_id: str) -> int:
    async with maker() as s:
        removed = await clear_world(s, project_id, world_id)
        await s.commit()
        return removed


async def clear_world(s, project_id: str, world_id: str) -> int:
    """A new plot replaces the old one: places, NPCs, maps and routes built for the old plot are removed.

    Plot anchors stay (the plot already re-synced them) and wait for the new places again. Runs in the caller's
    transaction; the stages built on the removed world are marked stale."""
    from sqlalchemy import delete, update

    from app.db.models import Entity, GeographyLink, GeographyNode, PlotAnchorBinding

    ids = list(await s.scalars(select(Entity.id).where(Entity.campaign_id == world_id)))
    if not ids:
        return 0
    await s.execute(delete(GeographyLink).where(GeographyLink.campaign_id == world_id))
    await s.execute(delete(GeographyNode).where(GeographyNode.campaign_id == world_id))
    await s.execute(delete(Entity).where(Entity.campaign_id == world_id))  # generation rows cascade
    await s.execute(
        update(PlotAnchorBinding)
        .where(PlotAnchorBinding.campaign_id == world_id)
        .values(holder_entity_id=None, target_location_id=None, state="reserved")
    )
    project = await s.get(AuthorProject, project_id)
    deps = dict(project.dependencies or {})
    stale = {r for r in deps.get("stale") or [] if r.startswith("stage:")}  # map refs of removed places are moot
    stale |= {f"stage:{down}" for down in downstream("plot") if down in deps}
    deps["stale"] = sorted(stale)
    project.dependencies = deps
    project.validation_report = None
    await s.flush()
    return len(ids)


async def materialize_stage(ctx: StageContext) -> dict:
    """Create every planned place and NPC and run the existing layout/geometry/contents phases."""
    from app.core.authoring.materialization import prepare_world
    from app.core.world_generation.service import Orchestrator

    preparer = Orchestrator(ctx.svc.coordination, getattr(ctx.svc, "bus", None), llm=getattr(ctx.svc, "llm", None))
    report = await prepare_world(ctx.svc.maker, ctx.project_id, preparer)
    if not report.complete:  # partial maps stay saved; the stage reports what is missing
        raise StageError("materialize_incomplete")
    return {"report": report.model_dump(mode="json")}


async def maps_stage(ctx: StageContext) -> dict:
    """Regenerate maps: the target location, or every location whose layout the author made stale."""
    from app.core.authoring.regeneration import regenerate_location
    from app.core.world_generation.service import Orchestrator

    async with ctx.svc.maker() as s:
        job = await s.get(AuthorJob, ctx.job_id)
        project = await s.get(AuthorProject, ctx.project_id)
        stale = list((project.dependencies or {}).get("stale") or [])
        targets = (
            [job.target_ref]
            if job.target_ref
            else sorted({r.split(":", 1)[1] for r in stale if r.startswith("layout:")})
        )
    preparer = Orchestrator(ctx.svc.coordination, getattr(ctx.svc, "bus", None), llm=getattr(ctx.svc, "llm", None))
    results = [await regenerate_location(ctx.svc.maker, ctx.project_id, ref, preparer) for ref in targets]
    if any(r["status"] != "ready" for r in results):
        raise StageError("maps_blocked")  # the previous maps stay in place
    return {"regenerated": [r["location_ref"] for r in results]}


async def geography_stage(ctx: StageContext) -> dict:
    """Compile regions, locations and routes from the plan into stored geography; no materialization."""
    from app.core.geography.compiler import compile_plan
    from app.core.geography.contracts import GeographyError
    from app.core.geography.storage import sync_geography

    async with ctx.svc.maker() as s:
        secret = await s.get(CampaignSecret, ctx.world_id)
        try:
            draft = compile_plan((secret.plot if secret else None) or {})
        except GeographyError as exc:
            raise StageError(exc.code) from exc
        entity_by_ref = {
            x["id"]: x["entity_id"]
            for x in ((secret.plot if secret else None) or {}).get("locations") or []
            if x.get("entity_id")
        }
        view = await sync_geography(s, ctx.world_id, draft, entity_by_ref)
        await s.commit()
    return {"nodes": len(view.nodes), "links": len(view.links)}


async def validate_stage(ctx: StageContext) -> dict:
    from app.core.authoring.validation import store_report, validate_project

    async with ctx.svc.maker() as s:
        project = await s.get(AuthorProject, ctx.project_id)
        report = await validate_project(s, project)
        await store_report(s, project, report)
        await s.commit()
    return {"errors": len(report.errors), "warnings": len(report.warnings), "source_revision": report.source_revision}


async def apply_lore(session, project: AuthorProject, result: dict) -> None:
    secret = await session.get(CampaignSecret, project.workspace_campaign_id)
    if secret is None:
        secret = CampaignSecret(campaign_id=project.workspace_campaign_id)
        session.add(secret)
    secret.setting = {**(secret.setting or {}), "lore": result["lore"]}


APPLY = {"lore": apply_lore}
HANDLERS: dict[str, Handler] = {
    "lore": lore_stage,
    "plot": plot_stage,
    "geography": geography_stage,
    "materialize": materialize_stage,
    "maps": maps_stage,
    "validate": validate_stage,
}


async def record_output(session, project: AuthorProject, job: AuthorJob, result: dict) -> None:
    """Short transaction: re-check inputs and revision, apply the result, publish the stage's output digest."""
    from app.core.authoring.jobs import stage_digest

    if job.stage != "validate":  # a report must not advance the revision it describes
        current = await session.scalar(select(AuthorProject.draft_revision).where(AuthorProject.id == project.id))
        await author_write(session, project, current)
    await session.refresh(project)
    if job.input_digest != await _expected(session, project, job, stage_digest):
        raise StageError("stale_input")
    apply = APPLY.get(job.stage)
    if apply is not None:
        await apply(session, project, result)
    deps = dict(project.dependencies or {})
    digest = output_digest(result)
    stale = set(deps.get("stale") or []) - {f"stage:{job.stage}"}  # this stage is current again
    if job.stage != "validate" and deps.get(job.stage) not in (None, digest):
        # a changed result makes everything built on it stale until rebuilt or accepted
        stale |= {f"stage:{down}" for down in downstream(job.stage) if down in deps}
    deps[job.stage] = digest
    deps["stale"] = sorted(stale)
    project.dependencies = deps


def downstream(stage: str) -> list[str]:
    from app.core.authoring.jobs import STAGES

    return [s for s in STAGES[STAGES.index(stage) + 1 :] if s != "validate"] if stage in STAGES else []


async def _expected(session, project, job, stage_digest) -> str:
    base = await stage_digest(session, project, job.stage, job.target_ref or None)
    # Regenerated variants carry a request-specific digest on top of the dependency digest.
    if job.input_digest == base:
        return base
    from app.core.authoring.jobs import _digest

    return _digest(base, "regen", job.request_key)
