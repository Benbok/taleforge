"""Library of published adventures (own projects) and independent game launch."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.authoring import version_out
from app.api.deps import SessionDep, UserDep
from app.core.authoring.contracts import LaunchReceipt, LaunchRequest, VersionOut
from app.core.authoring.instances import instantiate_adventure
from app.core.campaigns import AccessDenied, NotFound, is_admin
from app.db.models import AdventureVersion, AuthorProject

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


@router.post("/{version_id}/games", response_model=LaunchReceipt, status_code=201)
async def launch(
    version_id: str, body: LaunchRequest, request: Request, session: SessionDep, user: UserDep
) -> LaunchReceipt:
    row = (
        await session.execute(
            select(AdventureVersion, AuthorProject.owner_id)
            .join(AuthorProject, AuthorProject.id == AdventureVersion.project_id)
            .where(AdventureVersion.id == version_id)
        )
    ).first()
    if row is None or row[1] != user.id or not is_admin(user):
        raise NotFound("приключение не найдено")  # no hint whether someone else's version exists
    version = row[0]
    try:
        media_dir = getattr(getattr(request.app.state, "master", None), "media_dir", None)
        flags = request.app.state.settings.new_campaign_flags
        receipt = await instantiate_adventure(
            session, user, version, body.options, body.request_key, media_dir, flags=flags
        )
        await session.commit()
    except IntegrityError:  # a parallel request with the same key won: return its game
        await session.rollback()
        version = await session.get(AdventureVersion, version_id)
        receipt = await instantiate_adventure(session, user, version, body.options, body.request_key)
    return receipt
