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
    ImportPlotRequest,
    ImportResult,
    IntroOut,
    IntroRequest,
    IntroTextRequest,
    JobOut,
    PrepareRequest,
    ProjectDetail,
    ProjectSummary,
    ProjectView,
    PublishRequest,
    StageReceipt,
    StageTask,
    ValidationIssue,
    ValidationReport,
    VersionOut,
    WorldOverview,
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
    from app.db.models import AdventureVersion

    rows = list(
        await session.scalars(
            select(AuthorProject)
            .where(AuthorProject.owner_id == user.id, AuthorProject.archived_at.is_(None))
            .order_by(AuthorProject.updated_at.desc())
        )
    )
    latest: dict[str, AdventureVersion] = {}
    if rows:
        for v in await session.scalars(
            select(AdventureVersion).where(AdventureVersion.project_id.in_([p.id for p in rows]))
        ):
            if v.project_id not in latest or v.version > latest[v.project_id].version:
                latest[v.project_id] = v
    out = []
    for p in rows:
        v = latest.get(p.id)
        status = "draft" if v is None else "published" if v.source_revision == p.draft_revision else "changed"
        out.append(
            ProjectSummary(
                id=p.id,
                title=p.title,
                draft_revision=p.draft_revision,
                budget_usd=p.budget_usd,
                status=status,
                latest_version=v.version if v else None,
            )
        )
    return out


@router.post("/projects", response_model=ProjectDetail, status_code=201)
async def create(body: AuthorProjectCreate, session: SessionDep, user: UserDep) -> ProjectDetail:
    project = await create_project(session, user, body)
    await session.commit()
    return _detail(project, await session.get(Campaign, project.workspace_campaign_id))


@router.get("/projects/{project_id}", response_model=ProjectView)
async def project_view(
    project_id: str, session: SessionDep, user: UserDep, view: Annotated[View, Query()] = "summary"
) -> ProjectView:
    from app.core.authoring.contracts import PublishedBrief, ValidationSummary
    from app.db.models import AdventureVersion

    project = await require_project(session, user, project_id)
    world = await session.get(Campaign, project.workspace_campaign_id)
    report = project.validation_report or None
    versions = await session.scalars(
        select(AdventureVersion)
        .where(AdventureVersion.project_id == project.id)
        .order_by(AdventureVersion.version.desc())
    )
    return ProjectView(
        project=_detail(project, world),
        preparation=await jobs.stage_view(session, project.id, full=view == "full"),
        validation=ValidationSummary(
            source_revision=int(report.get("source_revision") or 0),
            errors=len(report.get("errors") or []),
            warnings=len(report.get("warnings") or []),
            current=report.get("source_revision") == project.draft_revision,
        )
        if report
        else None,
        published=[
            PublishedBrief(
                id=v.id, version=v.version, source_revision=v.source_revision, published_at=v.published_at.isoformat()
            )
            for v in versions
        ],
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
    from app.core.world_generation import storage

    layout = await storage.find(session, project.workspace_campaign_id, root.id, "location_layout")
    return AuthorMapOut(
        location_ref=location_ref, name=root.name, areas=out, layout_quality=layout.quality if layout else None
    )


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


@router.get("/projects/{project_id}/tasks/{stage}", response_model=StageTask)
async def stage_task(project_id: str, stage: Literal["lore", "plot"], session: SessionDep, user: UserDep) -> StageTask:
    """The stage's prompt and answer schema, to run it by hand in any outside model. Read-only, no model call."""
    from app.core.authoring.manual import task_for

    project = await require_project(session, user, project_id)
    return StageTask.model_validate(await task_for(session, project, stage))


@router.post("/projects/{project_id}/plot/import", response_model=ImportResult)
async def import_plot(project_id: str, body: ImportPlotRequest, session: SessionDep, user: UserDep):
    """A plot made elsewhere passes the architect's server check and then counts as a ready plot stage."""
    from app.core.authoring.manual import ImportRejected
    from app.core.authoring.manual import import_plot as do_import

    project = await require_project(session, user, project_id)
    try:
        result = await do_import(session, project, body.plan, body.expected_revision, body.request_key)
    except ImportRejected as exc:
        await session.rollback()
        return JSONResponse({"detail": "import_rejected", "errors": exc.errors[:50]}, status_code=409)
    await session.commit()
    return ImportResult.model_validate(result)


@router.get("/projects/{project_id}/overview", response_model=WorldOverview)
async def world_overview(project_id: str, session: SessionDep, user: UserDep) -> WorldOverview:
    """One picture of the prepared world: places with their areas, passages inside them, routes between them,
    who and what is where. Full author view, read-only."""
    from app.core.authoring.contracts import OverviewArea, OverviewLocation, OverviewPassage, OverviewRoute
    from app.core.geography.compiler import compile_plan
    from app.core.geography.contracts import GeographyError
    from app.core.layout import store as layout_store
    from app.db.models import CampaignSecret

    project = await require_project(session, user, project_id)
    secret = await session.get(CampaignSecret, project.workspace_campaign_id)
    plan = (secret.plot if secret else None) or {}
    entities = {
        e.id: e
        for e in await session.scalars(select(Entity).where(Entity.campaign_id == project.workspace_campaign_id))
    }
    inside: dict[str, list[Entity]] = {}
    for e in entities.values():
        if e.location_id:
            inside.setdefault(e.location_id, []).append(e)

    def residents(area_id: str) -> tuple[list[str], list[str]]:
        npcs, items, stack = [], [], list(inside.get(area_id, []))
        while stack:  # items inside containers and in NPC hands count for the area they are in
            e = stack.pop()
            st = e.state or {}
            if e.kind == "creature":
                npcs.append(e.name)
            elif st.get("item_ref") or st.get("plot_anchor"):
                items.append(e.name)
            stack.extend(inside.get(e.id, []))
        return sorted(npcs), sorted(items)

    locations = []
    for loc in plan.get("locations") or []:
        root = entities.get(loc.get("entity_id") or "")
        out = OverviewLocation(ref=loc["id"], name=loc.get("name") or loc["id"], region=loc.get("region"))
        if root is not None:
            bp = layout_store.blueprint_of(root)
            ids = layout_store.area_ids(root)
            parts = {p.get("ref"): p for p in (loc.get("spatial") or {}).get("parts") or []}
            for area_ref, area_id in (ids or {"": root.id}).items():
                area = entities.get(area_id)
                npcs, items = residents(area_id)
                out.areas.append(
                    OverviewArea(
                        area_ref=area_ref,
                        name=area.name if area else area_ref,
                        entry=bool(bp and bp.entry == area_ref),
                        secret=bool((parts.get(area_ref) or {}).get("secret")),
                        npcs=npcs,
                        items=items,
                    )
                )
            for p in bp.passages if bp else ():
                a, b = p.ends
                if a.area_ref is None and b.area_ref is None:
                    continue
                start, end = (a, b) if a.area_ref else (b, a)
                out.passages.append(
                    OverviewPassage(
                        from_area=start.area_ref, to_area=end.area_ref, name=p.public_name, kind=p.kind, hidden=p.hidden
                    )
                )
        locations.append(out)
    routes = []
    try:
        draft = compile_plan(plan)
        routes = [
            OverviewRoute(
                ref=r.ref,
                from_ref=r.source.node_ref,
                from_area=r.source.area_ref,
                to_ref=r.target.node_ref,
                to_area=r.target.area_ref,
                bidirectional=r.bidirectional,
                hidden=r.hidden,
            )
            for r in draft.links
        ]
    except GeographyError:
        pass  # the geography step reports the error; the overview shows what it can
    regions = {r["id"]: r.get("name") or r["id"] for r in plan.get("regions") or [] if r.get("id")}
    return WorldOverview(locations=locations, routes=routes, regions=regions)


def _intro_out(secret, plan: dict, tts) -> IntroOut:
    from app.agents import prelude

    ready = ((secret.setting if secret else None) or {}).get(prelude.INTRO_KEY) or {}
    providers = {name: bool(tts is not None and tts.get_engine(name).enabled) for name in ("voicestudio", "gemini")}
    return IntroOut(
        text=ready.get("text") or "",
        voices=[{"id": v["id"], "duration": v.get("duration")} for v in ready.get("voices") or [] if v.get("id")],
        provider=ready.get("provider"),
        voice=ready.get("voice"),
        parts=int(ready.get("parts") or 0),
        current=bool(ready.get("text")) and ready.get("version") == plan.get("version"),
        providers=providers,
    )


@router.get("/projects/{project_id}/intro", response_model=IntroOut)
async def intro_view(project_id: str, request: Request, session: SessionDep, user: UserDep) -> IntroOut:
    from app.db.models import CampaignSecret

    project = await require_project(session, user, project_id)
    secret = await session.get(CampaignSecret, project.workspace_campaign_id)
    return _intro_out(secret, (secret.plot if secret else None) or {}, getattr(request.app.state, "tts", None))


@router.post("/projects/{project_id}/intro", response_model=StageReceipt, status_code=202)
async def intro_prepare(project_id: str, body: IntroRequest, session: SessionDep, user: UserDep) -> StageReceipt:
    """Write and/or voice the intro as an author job; the chosen source decides the cost."""
    from app.core.authoring.intro import encode

    project = await require_project(session, user, project_id)
    receipt = await jobs.request_stage(
        session,
        project,
        "intro",
        encode(body.provider, body.voice, body.rewrite, body.voiced),
        body.expected_revision,
        body.request_key,
        regenerate=True,
    )
    await session.commit()
    return receipt


@router.put("/projects/{project_id}/intro/text", response_model=IntroOut)
async def intro_text(project_id: str, body: IntroTextRequest, request: Request, session: SessionDep, user: UserDep):
    from app.core.authoring.intro import drop_voices, set_text
    from app.core.authoring.projects import author_write
    from app.db.models import CampaignSecret

    project = await require_project(session, user, project_id)
    await author_write(session, project, body.expected_revision)
    old = await set_text(session, project, body.text)
    await session.commit()
    media_dir = getattr(request.app.state.master, "media_dir", None)
    if media_dir:
        drop_voices(media_dir, project.workspace_campaign_id, old.get("voices"))
    secret = await session.get(CampaignSecret, project.workspace_campaign_id)
    return _intro_out(secret, (secret.plot if secret else None) or {}, getattr(request.app.state, "tts", None))


@router.get("/projects/{project_id}/intro/voice/{voice_id}")
async def intro_voice(project_id: str, voice_id: str, request: Request, session: SessionDep, user: UserDep):
    from fastapi import Response

    from app.core import voice

    project = await require_project(session, user, project_id)
    meta, audio = voice.read(request.app.state.master.media_dir, project.workspace_campaign_id, voice_id)
    return Response(audio, media_type=meta["mime"], headers={"Cache-Control": "private, max-age=86400"})
