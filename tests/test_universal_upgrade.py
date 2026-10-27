"""Preserve the Node1 library and later game receipts across the real revision chain."""

import asyncio
from copy import deepcopy

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.db.models import Campaign, Character, Event, LibraryCharacter, User
from app.db.session import make_engine, make_sessionmaker, verify_universal_schema
from tests.test_universal_resolution import sheet


def test_upgrade_keeps_node1_hero_and_later_game_receipt(tmp_path):
    async def run():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'node1-upgrade.db'}")

        def upgrade(connection, revision):
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, revision)

        saved_sheet = sheet().model_dump(mode="json")
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: upgrade(conn, "universal_0001"))
            await connection.execute(
                User.__table__.insert().values(id="saved-owner", name="Saved", password_hash="test")
            )
            await connection.execute(
                LibraryCharacter.__table__.insert().values(
                    id="node1-original",
                    owner_user_id="saved-owner",
                    name="Original",
                    sheet=saved_sheet,
                    revision=1,
                )
            )
            await connection.execute(
                Campaign.__table__.insert().values(
                    id="saved-game",
                    owner_id="saved-owner",
                    name="Saved world",
                    ruleset_id="universal",
                    ruleset_version="universal.v1",
                )
            )
            await connection.execute(
                Character.__table__.insert().values(
                    id="saved-copy",
                    campaign_id="saved-game",
                    owner_user_id="saved-owner",
                    name="Copy",
                    status="active",
                    sheet=saved_sheet,
                    resources={"hp": "17"},
                )
            )
            await connection.run_sync(lambda conn: upgrade(conn, "head"))
        await verify_universal_schema(engine)
        maker = make_sessionmaker(engine)
        async with maker() as session:
            original = await session.get(LibraryCharacter, "node1-original")
            assert original.id == "node1-original" and original.sheet == saved_sheet
            assert original.revision == 1 and original.portrait_id is None
            hero = await session.get(Character, "saved-copy")
            hero.sheet = {**hero.sheet, "level": "2", "xp": "300"}
            receipt = Event(
                id="later-receipt",
                campaign_id="saved-game",
                actor_id=hero.id,
                tool="universal_action",
                idempotency_key="saved-action",
                payload={"cost": "3", "xp": "300", "marker": "immutable-result"},
            )
            session.add(receipt)
            await session.commit()
            before = deepcopy((hero.sheet, hero.resources, original.sheet, receipt.payload))
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: upgrade(conn, "head"))
        await verify_universal_schema(engine)
        async with maker() as session:
            hero = await session.get(Character, "saved-copy")
            original = await session.get(LibraryCharacter, "node1-original")
            receipt = await session.get(Event, "later-receipt")
            assert (hero.sheet, hero.resources, original.sheet, receipt.payload) == before
            assert len(list(await session.scalars(select(Event)))) == 1
        await engine.dispose()

    asyncio.run(run())
