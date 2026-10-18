"""Author workspace API. GET never starts work; summary projections carry no editor content."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.agents import author_editor
from app.api.deps import SessionDep, UserDep
from app.core.authoring import jobs
from app.core.authoring.contracts import (
    AcceptStaleRequest,
    AuthorMapArea,
    AuthorMapOut,
    AuthorProjectCreate,
    EditProposal,
    EditRequest,
    EditResult,
    EditsRequest,
    JobOut,
    PrepareRequest,
    ProjectDetail,
    ProjectSummary,
    ProjectView,
    PublishRequest,
    StageReceipt,
    ValidationIssue,
    ValidationReport,
    VersionOut,
)
from app.core.authoring.edits import accept_stale, apply_edits
from app.core.authoring.projects import create_project, require_project
from app.core.authoring.publication import PublishBlocked, publish_project
from app.core.authoring.validation import store_report, validate_project
from app.core.campaigns import AccessDenied, is_admin
from app.db.models import AuthorJob, AuthorProject, Campaign, Entity

router = APIRouter(prefix="/api/author", tags=["author"])
View = Literal["summary", "full"]


def _detail(project: AuthorProject, world: Campaign) -> ProjectDetail:
    return ProjectDetail(
        id=project.id,
        title=project.title,
        draft_revision=project.draft_revision,
        budget_usd=project.budget_usd,
        brief=world.brief or {},
    )


def _redact(report: ValidationReport) -> ValidationReport:
    """Spoiler-free projection: stable codes and counts only, no object names or refs."""
    strip = lambda issues: tuple(ValidationIssue(code=i.code) for i in issues)  # noqa: E731
    return report.model_copy(update={"errors": strip(report.errors), "warnings": strip(report.warnings)})


@router.get("/projects", response_model=list[ProjectSummary])
async def list_projects(session: SessionDep, user: UserDep) -> list[ProjectSummary]:
    if not is_admin(user):
        raise AccessDenied("пространство автора доступно только Admin")
    rows = await session.scalars(
        select(AuthorProject)
        .where(AuthorProject.owner_id == user.id, AuthorProject.archived_at.is_(None))
        .order_by(AuthorProject.updated_at.desc())
    )
    return [ProjectSummary.model_validate(p) for p in rows]


@router.post("/projects", response_model=ProjectDetail, status_code=201)
async def create(body: AuthorProjectCreate, session: SessionDep, user: UserDep) -> ProjectDetail:
    project = await create_project(session, user, body)
    await session.commit()
    return _detail(project, await session.get(Campaign, project.workspace_campaign_id))


@router.get("/projects/{project_id}", response_model=ProjectView)
async def project_view(
    project_id: str, session: SessionDep, user: UserDep, view: Annotated[View, Query()] = "summary"
) -> ProjectView:
    project = await require_project(session, user, project_id)
    world = await session.get(Campaign, project.workspace_campaign_id)
    return ProjectView(
        project=_detail(project, world), preparation=await jobs.stage_view(session, project.id, full=view == "full")
    )


@router.post("/projects/{project_id}/prepare", response_model=StageReceipt, status_code=202)
async def prepare(project_id: str, body: PrepareRequest, session: SessionDep, user: UserDep) -> StageReceipt:
    project = await require_project(session, user, project_id)
    receipt = await jobs.request_stage(
        session,
        project,
        body.stage,
        body.target_ref,
        body.expected_revision,
        body.request_key,
        regenerate=body.regenerate,
    )
    await session.commit()
    return receipt


@router.get("/projects/{project_id}/jobs", response_model=list[JobOut])
async def list_jobs(project_id: str, session: SessionDep, user: UserDep) -> list[JobOut]:
    project = await require_project(session, user, project_id)
    rows = await session.scalars(
        select(AuthorJob).where(AuthorJob.project_id == project.id).order_by(AuthorJob.created_at.desc()).limit(100)
    )
    return [JobOut.model_validate(j) for j in rows]


@router.post("/projects/{project_id}/edits/preview", response_model=EditProposal)
async def preview_edits(project_id: str, body: EditRequest, request: Request, session: SessionDep, user: UserDep):
    project = await require_project(session, user, project_id)
    pid = project.id
    await session.rollback()  # no transaction while the model thinks; nothing is written by a preview
    return await author_editor.propose(request.app.state.master, pid, body)


@router.post("/projects/{project_id}/edits", response_model=EditResult)
async def edits(project_id: str, body: EditsRequest, session: SessionDep, user: UserDep) -> EditResult:
    project = await require_project(session, user, project_id)
    result = await apply_edits(session, project, body.patch, body.expected_revision, body.request_key)
    await session.commit()
    return result


@router.post("/projects/{project_id}/edits/accept-stale", response_model=EditResult)
async def accept(project_id: str, body: AcceptStaleRequest, session: SessionDep, user: UserDep) -> EditResult:
    project = await require_project(session, user, project_id)
    result = await accept_stale(session, project, body.refs, body.expected_revision, body.request_key)
    await session.commit()
    return result


@router.get("/projects/{project_id}/maps/{location_ref}", response_model=AuthorMapOut)
async def author_map(project_id: str, location_ref: str, session: SessionDep, user: UserDep) -> AuthorMapOut:
    """Full authoring map, only on explicit request. Read-only: no visits, no hero, no player knowledge."""
    from app.core.layout import store as layout_store

    project = await require_project(session, user, project_id)
    entities = {
        e.id: e
        for e in await session.scalars(select(Entity).where(Entity.campaign_id == project.workspace_campaign_id))
    }
    from app.db.models import CampaignSecret

    secret = await session.get(CampaignSecret, project.workspace_campaign_id)
    sketch = next(
        (x for x in ((secret.plot if secret else None) or {}).get("locations") or [] if x["id"] == location_ref), {}
    )
    root = entities.get(sketch.get("entity_id") or "")  # the plot's current map, never a regeneration candidate
    if root is None:
        from app.core.campaigns import NotFound

        raise NotFound("карта не найдена")
    areas = layout_store.area_ids(root) or {"": root.id}
    out = []
    for area_ref, area_id in areas.items():
        area = entities.get(area_id)
        if area is None or not (area.state or {}).get("sketch"):
            continue
        out.append(
            AuthorMapArea(
                area_ref=area_ref,
                name=area.name,
                sketch=area.state["sketch"],
                ports=(area.state or {}).get("route_ports") or {},
            )
        )
    return AuthorMapOut(location_ref=location_ref, name=root.name, areas=out)


@router.post("/projects/{project_id}/validate", response_model=ValidationReport)
async def validate(
    project_id: str, session: SessionDep, user: UserDep, view: Annotated[View, Query()] = "summary"
) -> ValidationReport:
    project = await require_project(session, user, project_id)
    report = await validate_project(session, project)
    await store_report(session, project, report)
    await session.commit()
    return report if view == "full" else _redact(report)


@router.post("/projects/{project_id}/publish", response_model=VersionOut, status_code=201)
async def publish(project_id: str, body: PublishRequest, session: SessionDep, user: UserDep):
    project = await require_project(session, user, project_id)
    try:
        version = await publish_project(session, project, body.expected_revision, body.request_key)
    except PublishBlocked as exc:
        await session.rollback()
        # owner-only response: refs are needed to fix the draft, but never the bundle itself
        return JSONResponse(
            {"detail": "publication_blocked", "issues": [i.model_dump(mode="json") for i in exc.issues]},
            status_code=409,
        )
    await session.commit()
    return version_out(version)


def version_out(version) -> VersionOut:
    return VersionOut(
        id=version.id,
        project_id=version.project_id,
        version=version.version,
        source_revision=version.source_revision,
        public_summary=version.public_summary,
        published_at=version.published_at.isoformat(),
    )
