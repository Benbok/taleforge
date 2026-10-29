"""Revision-bound universal world studio, with author-owned facts and private reviews."""

from sqlalchemy import update

from app.agents.studio_review import ask_studio, draft_from_idea
from app.core.authoring.contracts import (
    CreationDialogue,
    StudioDraft,
    StudioFields,
    StudioView,
    ValidationIssue,
    ValidationReport,
)
from app.core.authoring.projects import author_write, require_project
from app.core.campaigns import Conflict
from app.db.models import AuthorProject, Campaign, CampaignSecret, User


def studio_fields(project: AuthorProject) -> StudioFields | None:
    data = (project.dependencies or {}).get("studio")
    return StudioFields.model_validate(data) if data is not None else None


def studio_view(project: AuthorProject) -> StudioView:
    fields = studio_fields(project)
    if fields is None:
        raise Conflict("studio_fields_required")
    receipt = (project.dependencies or {}).get("studio_review")
    review = None
    if receipt and receipt.get("source_revision") == project.draft_revision:
        review = CreationDialogue.model_validate(receipt["dialogue"])
    return StudioView(project_id=project.id, draft_revision=project.draft_revision, fields=fields, review=review)


async def save_studio(session, project: AuthorProject, expected_revision: int, fields: StudioFields) -> StudioView:
    await author_write(session, project, expected_revision)
    project.dependencies = {
        **(project.dependencies or {}),
        "studio": fields.model_dump(mode="json"),
        "studio_review": None,
    }
    project.title = fields.title
    world = await session.get(Campaign, project.workspace_campaign_id)
    world.name = fields.title
    world.ruleset_id, world.ruleset_version = "universal", "1"
    world.pack_id = world.pack_version = None
    world.content_chain = []
    world.difficulty, world.public_intro = fields.difficulty, fields.public_text
    secret = await session.get(CampaignSecret, world.id)
    secret.setting = {**(secret.setting or {}), "studio": fields.model_dump(mode="json")}
    await session.flush()
    return studio_view(project)


async def _owned(session, project_id: str, owner_id: str) -> AuthorProject:
    user = await session.get(User, owner_id)
    return await require_project(session, user, project_id)


async def lock_studio(session, project: AuthorProject, expected_revision: int) -> None:
    # Match author_write's lock order, without changing the content revision for a receipt.
    await session.execute(
        update(Campaign)
        .where(Campaign.id == project.workspace_campaign_id)
        .values(world_revision=Campaign.world_revision)
        .execution_options(synchronize_session=False)
    )
    changed = await session.scalar(
        update(AuthorProject)
        .where(
            AuthorProject.id == project.id,
            AuthorProject.draft_revision == expected_revision,
            AuthorProject.archived_at.is_(None),
        )
        .values(draft_revision=AuthorProject.draft_revision)
        .returning(AuthorProject.id)
        .execution_options(synchronize_session=False)
    )
    if changed is None:
        raise Conflict("stale_revision")
    await session.refresh(project)


async def review_project(
    session, project_id: str, owner_id: str, expected_revision: int, *, llm, answer: str = ""
) -> CreationDialogue:
    project = await _owned(session, project_id, owner_id)
    if project.draft_revision != expected_revision:
        raise Conflict("stale_revision")
    fields = studio_fields(project)
    if fields is None:
        raise Conflict("studio_fields_required")
    from app.core.authoring.publication import _digest

    original = _digest(fields.model_dump(mode="json"))
    previous = (project.dependencies or {}).get("studio_review") or {}
    transcript = list(previous.get("transcript") or []) if previous.get("source_revision") == expected_revision else []
    if answer:
        transcript.append(dict(role="user", content=answer))
    result = await ask_studio(session, llm, project.workspace_campaign_id, fields.model_dump(mode="json"), transcript)
    await lock_studio(session, project, expected_revision)
    if _digest(studio_fields(project).model_dump(mode="json")) != original:
        raise Conflict("stale_revision")
    missing = [key for key in ("premise", "world", "laws", "start") if not getattr(fields, key).strip()]
    question = result.question or ("Заполните поля: " + ", ".join(missing) if missing else None)
    dialogue = CreationDialogue(
        project_id=project.id,
        source_revision=expected_revision,
        status="questions" if question else "ready",
        question=question,
        notes=result.notes,
        suggestions=[x for x in result.suggestions if x.text.strip() != getattr(fields, x.field).strip()],
    )
    transcript.append(dict(role="assistant", content=question or "Мир готов к принятию."))
    project.dependencies = {
        **(project.dependencies or {}),
        "studio_review": dict(
            source_revision=expected_revision,
            source_digest=original,
            dialogue=dialogue.model_dump(mode="json"),
            transcript=transcript,
        ),
    }
    await session.flush()
    return dialogue


def validate_studio(project: AuthorProject) -> ValidationReport:
    from app.core.authoring.publication import _digest

    fields = studio_fields(project)
    digest = _digest(fields.model_dump(mode="json"))
    receipt = (project.dependencies or {}).get("studio_review") or {}
    ready = (
        receipt.get("source_revision") == project.draft_revision
        and receipt.get("source_digest") == digest
        and (receipt.get("dialogue") or {}).get("status") == "ready"
    )
    errors = () if ready else (ValidationIssue(code="studio_review_required"),)
    return ValidationReport(source_revision=project.draft_revision, source_digest=digest, errors=errors)


async def accept_project(
    session, project_id: str, owner_id: str, expected_revision: int, request_key: str | None = None
):
    from app.core.authoring.publication import publish_project

    project = await _owned(session, project_id, owner_id)
    if studio_fields(project) is None:
        raise Conflict("studio_fields_required")
    return await publish_project(
        session, project, expected_revision, request_key or f"studio-accept-{expected_revision}"
    )


async def draft_project(session, project_id: str, owner_id: str, idea: str, *, llm) -> StudioDraft:
    """A proposal only: nothing is saved, the author decides what to take."""
    project = await _owned(session, project_id, owner_id)
    fields = studio_fields(project)
    if fields is None:
        raise Conflict("studio_fields_required")
    return await draft_from_idea(session, llm, project.workspace_campaign_id, fields.title, idea)
