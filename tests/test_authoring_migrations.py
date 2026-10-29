"""Recover either historical meaning of revision 0031 without losing rows."""

import asyncio
import warnings
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.db.session import make_engine


def config():
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("path_separator", "os")
    return cfg


def test_migration_history_has_one_unambiguous_head():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert len(ScriptDirectory.from_config(config()).get_heads()) == 1


@pytest.mark.parametrize("usage_present", [False, True])
@pytest.mark.parametrize("jsonb_present", [False, True])
def test_postgres_repairs_both_historical_schemas(monkeypatch, database_url, usage_present, jsonb_present):
    if not database_url:
        pytest.skip("requires isolated TEST_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", database_url)

    async def prepare():
        engine = make_engine(database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DROP SCHEMA public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
                await conn.execute(text("CREATE TABLE llm_calls (id TEXT PRIMARY KEY, tokens_in INTEGER)"))
                await conn.execute(text("INSERT INTO llm_calls VALUES ('retained', 7)"))
                if usage_present:
                    for definition in ("tokens_cached INTEGER", "cost_known BOOLEAN", "diagnostics JSON"):
                        await conn.execute(text(f"ALTER TABLE llm_calls ADD COLUMN {definition}"))
                    await conn.execute(text("UPDATE llm_calls SET tokens_cached=4"))
                kind = "JSONB" if jsonb_present else "JSON"
                await conn.execute(
                    text(
                        f"CREATE TABLE party_map_memories (snapshot {kind}, "
                        f"discovered_passages {kind} NOT NULL DEFAULT '[]')"
                    )
                )
                await conn.execute(text('INSERT INTO party_map_memories VALUES (\'{"root_id":"keep"}\', \'["exit"]\')'))
        finally:
            await engine.dispose()

    asyncio.run(prepare())
    cfg = config()
    command.stamp(cfg, "0031")
    command.upgrade(cfg, "0033")

    async def verify():
        engine = make_engine(database_url)
        try:
            async with engine.connect() as conn:
                row = (await conn.execute(text("SELECT tokens_in, tokens_cached FROM llm_calls"))).one()
                assert row == (7, 4 if usage_present else None)
                row = (
                    await conn.execute(
                        text(
                            "SELECT snapshot, discovered_passages, pg_typeof(snapshot)::text, "
                            "pg_typeof(discovered_passages)::text FROM party_map_memories"
                        )
                    )
                ).one()
                assert row == ({"root_id": "keep"}, ["exit"], "jsonb", "jsonb")
        finally:
            await engine.dispose()

    asyncio.run(verify())
    command.downgrade(cfg, "0030")
    command.upgrade(cfg, "0033")


def test_postgres_fresh_migration_chain(monkeypatch, database_url):
    if not database_url:
        pytest.skip("requires isolated TEST_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", database_url)

    async def reset():
        engine = make_engine(database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("DROP SCHEMA public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
        finally:
            await engine.dispose()

    asyncio.run(reset())
    command.upgrade(config(), "head")
    command.check(config())
