"""Ownership-scoped library access; Universal services own creation and editing."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.campaigns import NotFound
from app.db.models import LibraryCharacter, User

MAX_HEROES = 30


async def list_mine(session: AsyncSession, user: User) -> list[LibraryCharacter]:
    q = select(LibraryCharacter).where(LibraryCharacter.owner_user_id == user.id)
    return list((await session.scalars(q.order_by(LibraryCharacter.created_at))).all())


async def get_mine(session: AsyncSession, user: User, lib_id: str) -> LibraryCharacter:
    lc = await session.get(LibraryCharacter, lib_id)
    if lc is None or lc.owner_user_id != user.id:
        raise NotFound("герой не найден")
    return lc
