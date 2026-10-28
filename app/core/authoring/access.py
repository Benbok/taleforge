"""Who may read the secrets an author put into a published world."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdventureVersion, AuthorProject, Campaign, User


async def author_secrets_visible(session: AsyncSession, campaign: Campaign, user: User) -> bool:
    """A game launched from a published world keeps the author's plot and setting from every other administrator,
    including the one who owns the game. A game that was not launched from a world has no author to hide from."""
    if campaign.adventure_version_id is None:
        return True
    owner_id = await session.scalar(
        select(AuthorProject.owner_id)
        .join(AdventureVersion, AdventureVersion.project_id == AuthorProject.id)
        .where(AdventureVersion.id == campaign.adventure_version_id)
    )
    return owner_id == user.id
