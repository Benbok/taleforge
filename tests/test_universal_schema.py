import asyncio
import io
import logging
import re
import runpy
from types import SimpleNamespace

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.db.session import make_engine


def test_fresh_schema_has_one_head():
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    assert len(heads) == 1
    assert ScriptDirectory.from_config(Config("alembic.ini")).get_base() == "universal_0001"


def test_embedded_migrations_preserve_application_logging(tmp_path):
    from app.db.session import verify_universal_schema

    logger = logging.getLogger("taleforge.schema_startup_probe")
    logger.disabled = False

    async def run():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'logging.db'}")
        try:
            await verify_universal_schema(engine)
            assert not logger.disabled
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_baseline_boolean_defaults_compile_for_postgresql(monkeypatch):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    # The baseline checks for existing tables; an offline compiler has no catalog.
    monkeypatch.setattr("sqlalchemy.inspect", lambda _: SimpleNamespace(get_table_names=lambda: []))
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    migration = runpy.run_path("alembic/versions/0001_universal_initial.py")
    with Operations.context(context):
        migration["upgrade"]()
    sql = output.getvalue()
    assert re.search(r"menu_music_enabled BOOLEAN DEFAULT true", sql, re.I)
    assert not re.search(r"BOOLEAN DEFAULT [01]\b", sql, re.I)


def test_postgresql_upgrade_creates_deferred_adventure_foreign_key(monkeypatch):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    monkeypatch.setattr(
        "sqlalchemy.inspect", lambda _: SimpleNamespace(get_table_names=lambda: [], get_foreign_keys=lambda table: [])
    )
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    baseline = runpy.run_path("alembic/versions/0001_universal_initial.py")
    deferred_fk = runpy.run_path("alembic/versions/0002_universal_deferred_fk.py")
    with Operations.context(context):
        baseline["upgrade"]()
        deferred_fk["upgrade"]()
    assert (
        "ALTER TABLE campaigns ADD CONSTRAINT fk_campaign_adventure_version "
        "FOREIGN KEY(adventure_version_id) REFERENCES adventure_versions (id)"
    ) in output.getvalue()


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
