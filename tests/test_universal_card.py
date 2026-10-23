import asyncio

from app.db.models import LibraryCharacter, User
from app.db.session import make_engine, make_sessionmaker
from app.rules.universal.contracts import AbilityScores, HeroDescription, UniversalSheet


def test_card_without_catalog_and_private_history(client, root):
    async def seed():
        engine = make_engine(client.app.state.settings.database_url)
        try:
            async with make_sessionmaker(engine)() as session:
                from sqlalchemy import select
                user = await session.scalar(select(User).where(User.name == 'root'))
                sheet = UniversalSheet(abilities=AbilityScores(str=8, dex=12, con=14, int=13, wis=15, cha=10),
                                       description=HeroDescription(name='Ivy', identity='Plant mage', capabilities='Vines'))
                hero = LibraryCharacter(owner_user_id=user.id, name='Ivy', sheet=sheet.model_dump(mode='json'),
                                        private_backstory='SECRET')
                session.add(hero)
                await session.commit()
                return hero.id
        finally:
            await engine.dispose()
    hero_id = asyncio.run(seed())
    response = client.get(f'/api/me/characters/{hero_id}', headers=root)
    assert response.status_code == 200, response.text
    card = response.json()
    assert card['derived']['hp_max'] == '24'
    assert card['derived']['ac'] == '13'
    assert card['equipment'] == card['learned_abilities'] == []
    assert card['sheet']['description']['capabilities'] == 'Vines'
    assert 'SECRET' not in response.text
    assert 'death_failures' not in response.text
    assert client.get(f'/api/me/characters/{hero_id}', headers={}).status_code == 401
