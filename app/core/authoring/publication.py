"""Immutable publication: a checked bundle is stored once and never rewritten."""

import hashlib
import json

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authoring.contracts import ValidationIssue
from app.core.authoring.snapshot import SnapshotError, export_bundle, validate_bundle
from app.core.authoring.validation import validate_project
from app.core.campaigns import Conflict
from app.db.models import AdventureVersion, AuthorProject


class PublishBlocked(Conflict):
    """Publication refused; ``issues`` says why. The draft and earlier versions are untouched."""

    def __init__(self, issues: tuple[ValidationIssue, ...]):
        super().__init__("publication_blocked")
        self.issues = issues


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _summary(bundle) -> dict:
    plot = bundle.plot
    return {
        "title": plot.get("title") or bundle.meta.get("name"),
        "tagline": plot.get("tagline") or "",
        "tags": list(plot.get("tags") or []),
        "intro": bundle.meta.get("public_intro") or plot.get("public_intro") or "",
        "locations": len(plot.get("locations") or []),
        "ruleset": bundle.meta.get("ruleset_id"),
    }


async def publish_project(
    session: AsyncSession, project: AuthorProject, expected_revision: int, request_key: str
) -> AdventureVersion:
    request_digest = _digest({"expected_revision": expected_revision})
    same = await session.scalar(
        select(AdventureVersion).where(
            AdventureVersion.project_id == project.id, AdventureVersion.publish_request_key == request_key
        )
    )
    if same is not None:
        if same.publish_input_digest != request_digest:
            raise Conflict("request_key уже использован для другой публикации")
        return same  # a repeated request returns the same version
    # Lock the draft at the expected revision: a concurrent edit makes this fail instead of mixing snapshots.
    locked = await session.scalar(
        update(AuthorProject)
        .where(AuthorProject.id == project.id, AuthorProject.draft_revision == expected_revision)
        .values(draft_revision=AuthorProject.draft_revision)
        .returning(AuthorProject.id)
        .execution_options(synchronize_session=False)
    )
    if locked is None:
        raise Conflict("stale_revision")
    await session.refresh(project)
    stored = project.validation_report
    if not stored or stored.get("source_revision") != project.draft_revision:
        raise Conflict("validation_required")  # an old report never authorizes a changed draft
    report = await validate_project(session, project)
    if report.errors:
        raise PublishBlocked(report.errors)
    try:
        bundle = await export_bundle(session, project)
    except SnapshotError as exc:
        raise PublishBlocked((ValidationIssue(code=exc.code, object_ref=exc.where),)) from exc
    broken = validate_bundle(bundle)
    if broken:
        raise PublishBlocked(broken)
    body = bundle.model_dump(mode="json")
    version = AdventureVersion(
        project_id=project.id,
        version=int(
            await session.scalar(
                select(func.coalesce(func.max(AdventureVersion.version), 0)).where(
                    AdventureVersion.project_id == project.id
                )
            )
        )
        + 1,
        source_revision=project.draft_revision,
        source_digest=_digest(body),
        publish_request_key=request_key,
        publish_input_digest=request_digest,
        public_summary=_summary(bundle),
        bundle=body,
        validation_report=report.model_dump(mode="json"),
    )
    session.add(version)
    await session.flush()
    return version
