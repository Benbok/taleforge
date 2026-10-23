from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.campaigns import NotFound
from app.db.models import LibraryCharacter


async def load_library_hero(session: AsyncSession, owner_id: str, hero_id: str) -> LibraryCharacter:
    hero = await session.scalar(select(LibraryCharacter).where(
        LibraryCharacter.id == hero_id, LibraryCharacter.owner_user_id == owner_id,
    ))
    if hero is None:
        raise NotFound("герой не найден")
    return hero
