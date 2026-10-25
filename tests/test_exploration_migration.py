import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.db.models import Campaign, Character, Event, UniversalClock, UniversalEffect, User
from app.db.session import make_engine, make_sessionmaker


def test_upgrade_existing_universal_database_preserves_saved_game(tmp_path):
    async def run():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'upgrade.db'}")

        def migrate(connection, target):
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, target)

        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: migrate(conn, "universal_0004"))
        maker = make_sessionmaker(engine)
        async with maker() as s:
            s.add(User(id="owner", name="Owner", password_hash="test"))
            await s.flush()
            s.add(
                Campaign(
                    id="game",
                    owner_id="owner",
                    name="Saved world",
                    ruleset_id="universal",
                    ruleset_version="universal.v1",
                )
            )
            await s.flush()
            s.add(
                Character(
                    id="saved-hero",
                    campaign_id="game",
                    owner_user_id="owner",
                    name="Saved hero",
                    status="active",
                    sheet={"original": True},
                    resources={"hp": "22"},
                )
            )
            s.add(Event(id="receipt", campaign_id="game", tool="universal_action", payload={"original": True}))
            await s.commit()
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: migrate(conn, "universal_0005"))
        async with maker() as s:
            s.add(UniversalClock(campaign_id="game", game_seconds=str(10**30), step_index="2"))
            s.add(
                UniversalEffect(
                    id="saved-effect",
                    campaign_id="game",
                    source_actor_id="saved-hero",
                    source_event_id="receipt",
                    target_id="saved-hero",
                    component="light",
                    definition={"kind": "illumination"},
                    starts_seconds=str(10**30),
                    ends_seconds=str(10**30 + 18),
                    status="active",
                )
            )
            await s.commit()
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: migrate(conn, "head"))
            tables = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
            assert {"universal_clocks", "universal_steps", "universal_effects", "universal_exchanges"} <= tables
        async with maker() as s:
            assert (await s.get(Campaign, "game")).name == "Saved world"
            assert (await s.get(Event, "receipt")).payload == {"original": True}
            assert (await s.get(Character, "saved-hero")).resources == {"hp": "22"}
            assert (await s.get(UniversalEffect, "saved-effect")).ends_seconds == str(10**30 + 18)
            assert (await s.get(UniversalClock, "game")).game_seconds == str(10**30)
        await engine.dispose()

    asyncio.run(run())
