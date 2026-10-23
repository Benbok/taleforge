import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.db.session import make_engine


def test_portrait_migration_preserves_existing_universal_hero(tmp_path):
    async def run():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
        try:
            async with engine.begin() as connection:

                def migrate(conn):
                    config = Config("alembic.ini")
                    config.attributes["connection"] = conn
                    command.upgrade(config, "universal_0002")
                    conn.execute(
                        text(
                            "INSERT INTO users (id,name,password_hash,platform_role,created_at) "
                            "VALUES ('u1','Owner','hash','player',CURRENT_TIMESTAMP)"
                        )
                    )
                    conn.execute(
                        text(
                            "INSERT INTO library_characters "
                            "(id,owner_user_id,name,revision,sheet,public_bio,private_backstory,"
                            "personality,created_at,updated_at) "
                            "VALUES ('lc1','u1','Existing',7,'{}','','','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                        )
                    )
                    command.upgrade(config, "head")
                    columns = {c["name"] for c in inspect(conn).get_columns("library_characters")}
                    assert {"portrait_id", "portrait_job_id"} <= columns
                    assert conn.execute(text("SELECT name,revision,portrait_id FROM library_characters")).one() == (
                        "Existing",
                        7,
                        None,
                    )
                    command.check(config)

                await connection.run_sync(migrate)
        finally:
            await engine.dispose()

    asyncio.run(run())
