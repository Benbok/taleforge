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
    return {"plan_version_id": version_id}


async def materialize_stage(ctx: StageContext) -> dict:
    """Create every planned place and NPC and run the existing layout/geometry/contents phases."""
    from app.core.authoring.materialization import prepare_world
    from app.core.world_generation.service import Orchestrator

    preparer = Orchestrator(ctx.svc.coordination, getattr(ctx.svc, "bus", None), llm=getattr(ctx.svc, "llm", None))
    report = await prepare_world(ctx.svc.maker, ctx.project_id, preparer)
    if not report.complete:  # partial maps stay saved; the stage reports what is missing
        raise StageError("materialize_incomplete")
    return {"report": report.model_dump(mode="json")}


async def apply_lore(session, project: AuthorProject, result: dict) -> None:
    secret = await session.get(CampaignSecret, project.workspace_campaign_id)
    if secret is None:
        secret = CampaignSecret(campaign_id=project.workspace_campaign_id)
        session.add(secret)
    secret.setting = {**(secret.setting or {}), "lore": result["lore"]}


APPLY = {"lore": apply_lore}
HANDLERS: dict[str, Handler] = {"lore": lore_stage, "plot": plot_stage, "materialize": materialize_stage}


async def record_output(session, project: AuthorProject, job: AuthorJob, result: dict) -> None:
    """Short transaction: re-check inputs and revision, apply the result, publish the stage's output digest."""
    from app.core.authoring.jobs import stage_digest

    current = await session.scalar(select(AuthorProject.draft_revision).where(AuthorProject.id == project.id))
    await author_write(session, project, current)
    await session.refresh(project)
    if job.input_digest != await _expected(session, project, job, stage_digest):
        raise StageError("stale_input")
    apply = APPLY.get(job.stage)
    if apply is not None:
        await apply(session, project, result)
    project.dependencies = {**(project.dependencies or {}), job.stage: output_digest(result)}


async def _expected(session, project, job, stage_digest) -> str:
    base = await stage_digest(session, project, job.stage, job.target_ref or None)
    # Regenerated variants carry a request-specific digest on top of the dependency digest.
    if job.input_digest == base:
        return base
    from app.core.authoring.jobs import _digest

    return _digest(base, "regen", job.request_key)
