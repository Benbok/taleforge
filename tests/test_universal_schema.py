import asyncio

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.db.session import make_engine


def test_fresh_schema_has_one_head():
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    assert heads == ["universal_0001"]


def test_nonempty_legacy_schema_is_rejected_before_writes(tmp_path):
    from app.db.session import verify_universal_schema

    async def run():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
        try:
            async with engine.begin() as conn:
                await conn.execute(text("create table users (id text primary key, name text)"))
                await conn.execute(text("insert into users values ('old', 'preserve')"))
            with pytest.raises(RuntimeError, match="universal"):
                await verify_universal_schema(engine)
            async with engine.connect() as conn:
                assert (await conn.execute(text("select name from users"))).scalar() == "preserve"
                assert await conn.run_sync(lambda c: inspect(c).get_table_names()) == ["users"]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_fresh_startup_and_restart_keep_hero(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}",
        superadmin_name="root",
        superadmin_password="password",
        voicestudio_api_base="",
    )
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/auth/login", json={"name": "root", "password": "password"}).status_code == 200
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/auth/login", json={"name": "root", "password": "password"}).status_code == 200
