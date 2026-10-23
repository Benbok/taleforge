import asyncio

import pytest

from app.core.campaigns import NotFound
from app.db.models import LibraryCharacter, User
from app.db.session import make_engine, make_sessionmaker


def test_restart_keeps_hero_and_foreign_library_hero_hidden(settings):
    from app.core.universal.state import load_library_hero

    async def run():
        engine = make_engine(settings.database_url)
        maker = make_sessionmaker(engine)
        try:
            async with maker() as session:
                user = User(name='owner', password_hash='unused')
                session.add(user)
                await session.flush()
                hero = LibraryCharacter(owner_user_id=user.id, name='Hero', sheet={'level': '1'})
                session.add(hero)
                await session.commit()
                hero_id, owner_id = hero.id, user.id
            async with maker() as session:
                assert (await load_library_hero(session, owner_id, hero_id)).id == hero_id
                with pytest.raises(NotFound):
                    await load_library_hero(session, 'someone-else', hero_id)
        finally:
            await engine.dispose()
    asyncio.run(run())
