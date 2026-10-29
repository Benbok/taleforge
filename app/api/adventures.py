"""Library of published adventures (own projects) and independent game launch."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.authoring import version_out
from app.api.deps import SessionDep, UserDep
from app.core.authoring.contracts import CatalogEntryOut, InstanceOptions, LaunchReceipt, LaunchRequest, VersionOut
from app.core.authoring.instances import instantiate_adventure
from app.core.authoring.projects import is_listed
from app.core.campaigns import AccessDenied, Conflict, NotFound, is_admin
from app.db.models import AdventureVersion, AuthorProject, Campaign, User

router = APIRouter(prefix="/api/adventures", tags=["adventures"])


@router.get("", response_model=list[VersionOut])
async def library(session: SessionDep, user: UserDep) -> list[VersionOut]:
    """Own published versions with a public summary; the bundle is never part of a list."""
    if not is_admin(user):
        raise AccessDenied("библиотека доступна только Admin")
    rows = await session.execute(
        select(AdventureVersion, AuthorProject.title)
        .join(AuthorProject, AuthorProject.id == AdventureVersion.project_id)
        .where(AuthorProject.owner_id == user.id)
        .order_by(AdventureVersion.published_at.desc())
    )
    return [version_out(v, title) for v, title in rows]


@router.get("/catalog", response_model=list[CatalogEntryOut])
async def catalog(session: SessionDep, user: UserDep) -> list[CatalogEntryOut]:
    """The latest published version of every author's world, newest first. Public summary only."""
    latest = (
        select(AdventureVersion.project_id, func.max(AdventureVersion.version).label("version"))
        .group_by(AdventureVersion.project_id)
        .subquery()
    )
    rows = await session.execute(
        select(AdventureVersion, AuthorProject, User.name)
        .join(
            latest,
            (latest.c.project_id == AdventureVersion.project_id) & (latest.c.version == AdventureVersion.version),
        )
        .join(AuthorProject, AuthorProject.id == AdventureVersion.project_id)
        .join(User, User.id == AuthorProject.owner_id)
        .where(AuthorProject.archived_at.is_(None))
        .order_by(AdventureVersion.published_at.desc())
    )
    return [
        CatalogEntryOut(
            version_id=v.id,
            project_id=v.project_id,
            title=project.title,
            author_name=author,
            version=v.version,
            public_summary=v.public_summary,
            published_at=v.published_at.isoformat(),
        )
        for v, project, author in rows
        if is_listed(project)
    ]


@router.post("/{version_id}/games", response_model=LaunchReceipt, status_code=201)
async def launch(
    version_id: str, body: LaunchRequest, request: Request, session: SessionDep, user: UserDep
) -> LaunchReceipt:
    row = (
        await session.execute(
            select(AdventureVersion, AuthorProject)
            .join(AuthorProject, AuthorProject.id == AdventureVersion.project_id)
            .where(AdventureVersion.id == version_id)
        )
    ).first()
    if row is None or not is_admin(user):
        raise NotFound("приключение не найдено")  # no hint whether the version exists
    version, project = row
    author_id, title = project.owner_id, project.title
    if project.archived_at is not None or (author_id != user.id and not is_listed(project)):
        raise NotFound("приключение не найдено")  # archived for everyone, hidden from everyone but the author
    if author_id != user.id:
        newest = await session.scalar(
            select(func.max(AdventureVersion.version)).where(AdventureVersion.project_id == version.project_id)
        )
        if version.version != newest:  # the catalog offers only the latest version of a foreign world
            raise NotFound("приключение не найдено")
    if body.options is None:
        # a retry with the same key must find its game even if the author renamed the world meanwhile
        same = await session.scalar(
            select(Campaign).where(Campaign.owner_id == user.id, Campaign.launch_request_key == body.request_key)
        )
        if same is not None and same.adventure_version_id == version.id:
            return LaunchReceipt(campaign_id=same.id, adventure_version_id=version.id, url=f"/c/{same.id}")
    options = body.options or InstanceOptions(name=title)
    if author_id != user.id and options.master.type == "owner":
        # the human master reads the whole world; only the author may do that with their own secrets
        raise Conflict("мастером за столом чужого мира может быть только ИИ")
    try:
        media_dir = getattr(getattr(request.app.state, "master", None), "media_dir", None)
        flags = request.app.state.settings.new_campaign_flags
        receipt = await instantiate_adventure(session, user, version, options, body.request_key, media_dir, flags=flags)
        await session.commit()
    except IntegrityError:  # a parallel request with the same key won: return its game
        await session.rollback()
        version = await session.get(AdventureVersion, version_id)
        receipt = await instantiate_adventure(session, user, version, options, body.request_key)
    return receipt
