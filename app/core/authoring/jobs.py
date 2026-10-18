"""Persistent author stage queue: idempotent requests, leases and budget reservation."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authoring.contracts import PreparationView, StageReceipt, StageStatus
from app.core.campaigns import Conflict
from app.db.models import AuthorJob, AuthorProject, Campaign, CampaignSecret, LlmCall

STAGES = ("lore", "plot", "geography", "materialize", "maps", "validate", "intro")
UPSTREAM = {
    "lore": None,
    "plot": "lore",
    "geography": "plot",
    "materialize": "geography",
    "maps": "materialize",
    "validate": "maps",
    "intro": "plot",  # the recorded intro follows the plot: a new plot makes it stale
}
# A stage needs the previous one ready. The plot may start from the brief alone; validation runs any time.
REQUIRED_UPSTREAM = {"geography": "plot", "materialize": "geography", "maps": "materialize", "intro": "plot"}


async def missing_upstream(session: AsyncSession, project: AuthorProject, stage: str) -> str | None:
    """Readiness is about content, not who made it: a plot written or imported by hand counts as ready."""
    upstream = REQUIRED_UPSTREAM.get(stage)
    if upstream is None:
        return None
    if upstream == "plot":
        secret = await session.get(CampaignSecret, project.workspace_campaign_id)
        return None if ((secret.plot if secret else None) or {}).get("locations") else "plot"
    return None if upstream in (project.dependencies or {}) else upstream


LEASE = timedelta(minutes=10)
ACTIVE = ("queued", "running")


def _digest(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


async def stage_digest(session: AsyncSession, project: AuthorProject, stage: str, target_ref: str | None) -> str:
    """Input digest comes from the stage's own dependencies, so unrelated edits do not invalidate it."""
    world = await session.get(Campaign, project.workspace_campaign_id)
    upstream = UPSTREAM[stage]
    base = {"brief": world.brief, "title": project.title, "pack": [world.pack_id, world.pack_version]}
    if upstream is None:
        return _digest(stage, target_ref or "", base)
    ready = (project.dependencies or {}).get(upstream)
    return _digest(stage, target_ref or "", base, upstream, ready)


def _receipt(job: AuthorJob) -> StageReceipt:
    return StageReceipt(job_id=job.id, stage=job.stage, status=job.status, source_revision=job.source_revision)


async def request_stage(
    session: AsyncSession,
    project: AuthorProject,
    stage: str,
    target_ref: str | None,
    expected_revision: int,
    request_key: str,
    *,
    regenerate: bool = False,
) -> StageReceipt:
    if stage not in STAGES:
        raise Conflict("неизвестный этап")
    request_digest = _digest(stage, target_ref or "", regenerate)
    same_key = await session.scalar(
        select(AuthorJob).where(AuthorJob.project_id == project.id, AuthorJob.request_key == request_key)
    )
    if same_key is not None:
        if same_key.request_digest != request_digest:
            raise Conflict("request_key уже использован для другого запроса")
        return _receipt(same_key)
    if project.draft_revision != expected_revision:
        raise Conflict("stale_revision")
    missing = await missing_upstream(session, project, stage)
    if missing:
        raise Conflict(f"upstream_not_ready: сначала этап {missing}")
    digest = await stage_digest(session, project, stage, target_ref)
    existing = await session.scalar(
        select(AuthorJob).where(
            AuthorJob.project_id == project.id,
            AuthorJob.stage == stage,
            AuthorJob.target_ref == (target_ref or ""),
            AuthorJob.input_digest == digest,
            AuthorJob.status.in_((*ACTIVE, "ready")),
        )
    )
    if existing is not None and not (regenerate and existing.status == "ready"):
        return _receipt(existing)
    if regenerate:  # новый вариант не затирает прежний результат: digest уникален по запросу
        digest = _digest(digest, "regen", request_key)
    job = AuthorJob(
        project_id=project.id,
        stage=stage,
        target_ref=target_ref or "",
        input_digest=digest,
        source_revision=project.draft_revision,
        request_key=request_key,
        request_digest=request_digest,
    )
    session.add(job)
    await session.flush()
    return _receipt(job)


async def due_job_ids(session: AsyncSession) -> list[str]:
    rows = await session.scalars(
        select(AuthorJob.id).where(
            or_(
                AuthorJob.status == "queued",
                (AuthorJob.status == "running") & (AuthorJob.lease_until < _now()),
            )
        )
    )
    return list(rows)


async def claim(session: AsyncSession, job_id: str) -> str | None:
    """Take the lease atomically; returns the lease token, or None if another worker owns it."""
    token = uuid.uuid4().hex
    now = _now()
    taken = await session.scalar(
        update(AuthorJob)
        .where(
            AuthorJob.id == job_id,
            or_(AuthorJob.status == "queued", (AuthorJob.status == "running") & (AuthorJob.lease_until < now)),
        )
        .values(status="running", lease_token=token, lease_until=now + LEASE, attempt_count=AuthorJob.attempt_count + 1)
        .returning(AuthorJob.id)
        .execution_options(synchronize_session=False)
    )
    return token if taken else None


async def finish(
    session: AsyncSession,
    job_id: str,
    token: str,
    status: str,
    *,
    result: dict | None = None,
    error_code: str | None = None,
) -> bool:
    """A worker whose lease was taken over matches no row, so it cannot overwrite a newer result."""
    values: dict = {"status": status, "error_code": error_code, "lease_token": None, "lease_until": None}
    if result is not None:
        values["result"] = result
    done = await session.scalar(
        update(AuthorJob)
        .where(AuthorJob.id == job_id, AuthorJob.lease_token == token, AuthorJob.status == "running")
        .values(**values)
        .returning(AuthorJob.id)
        .execution_options(synchronize_session=False)
    )
    return done is not None


async def spend(session: AsyncSession, project_id: str) -> tuple[float, bool]:
    """Spent USD and whether any provider cost is unknown (never counted as a confirmed zero)."""
    total, unknown = (
        await session.execute(
            select(func.coalesce(func.sum(LlmCall.cost), 0), func.count().filter(LlmCall.cost_known.is_not(True)))
            .join(AuthorJob, AuthorJob.id == LlmCall.author_job_id)
            .where(AuthorJob.project_id == project_id)
        )
    ).one()
    return float(total or 0), bool(unknown)


async def reserve(session: AsyncSession, project: AuthorProject, job_id: str, estimate_usd: float) -> bool:
    """Reserve the upper estimate before a call; False means the budget cannot cover it."""
    if project.budget_usd is not None:
        spent, _ = await spend(session, project.id)
        held = await session.scalar(
            select(func.coalesce(func.sum(AuthorJob.reserved_usd), 0)).where(
                AuthorJob.project_id == project.id, AuthorJob.status == "running", AuthorJob.id != job_id
            )
        )
        if spent + float(held or 0) + estimate_usd > project.budget_usd:
            return False
    await session.execute(update(AuthorJob).where(AuthorJob.id == job_id).values(reserved_usd=estimate_usd))
    return True


async def stage_view(session: AsyncSession, project_id: str, *, full: bool) -> PreparationView:
    project = await session.get(AuthorProject, project_id)
    stages = []
    for stage in STAGES:
        # A newer failed/blocked attempt does not hide an earlier ready result.
        job = await session.scalar(
            select(AuthorJob)
            .where(AuthorJob.project_id == project_id, AuthorJob.stage == stage)
            .order_by(AuthorJob.created_at.desc(), AuthorJob.id.desc())
            .limit(1)
        )
        manual = job is None and stage in (project.dependencies or {})  # written or imported by the author
        stages.append(
            StageStatus(
                stage=stage,
                status=("manual" if manual else "not_requested") if job is None else job.status,
                job_id=job.id if job else None,
                error_code=job.error_code if job else None,
                source_revision=job.source_revision if job else None,
            )
        )
    spent, unknown = await spend(session, project_id)
    content = None
    if full:
        secret = await session.get(CampaignSecret, project.workspace_campaign_id)
        content = {"setting": secret.setting, "plot": secret.plot} if secret else {}
    return PreparationView(
        project_id=project_id,
        draft_revision=project.draft_revision,
        stages=tuple(stages),
        spent_usd=spent,
        budget_usd=project.budget_usd,
        cost_unknown=unknown,
        stale=tuple((project.dependencies or {}).get("stale") or ()),
        content=content,
    )
