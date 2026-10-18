"""Recover either historical meaning of revision 0031 without losing rows."""

import asyncio
import sqlite3
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
@pytest.mark.parametrize("stamped", [False, True])
def test_upgrade_repairs_ambiguous_0031(monkeypatch, tmp_path, usage_present, stamped):
    path = tmp_path / "author-migrations.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    cfg = config()
    command.upgrade(cfg, "0030")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO llm_calls (id, purpose, model, tokens_in, tokens_out, cost, latency_ms, created_at) "
            "VALUES ('retained', 'test', 'fixture', 7, 3, 0.25, 1, '2026-10-18')"
        )
        if usage_present:
            db.execute("ALTER TABLE llm_calls ADD COLUMN tokens_cached INTEGER")
            db.execute("ALTER TABLE llm_calls ADD COLUMN cost_known BOOLEAN")
            db.execute("ALTER TABLE llm_calls ADD COLUMN diagnostics JSON")
            db.execute("UPDATE llm_calls SET tokens_cached=4, cost_known=1, diagnostics='{}'")
        if stamped:
            db.execute("UPDATE alembic_version SET version_num='0031'")
    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT tokens_in, cost FROM llm_calls WHERE id='retained'").fetchone() == (7, 0.25)
        assert {"tokens_cached", "cost_known", "diagnostics"} <= {
            row[1] for row in db.execute("PRAGMA table_info(llm_calls)")
        }
        if usage_present:
            assert db.execute("SELECT tokens_cached FROM llm_calls").fetchone() == (4,)
    command.downgrade(cfg, "0030")
    command.upgrade(cfg, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM llm_calls").fetchone() == (1,)


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


def test_foundation_preserves_existing_game_and_children(monkeypatch, tmp_path):
    path = tmp_path / "existing-game.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    cfg = config()
    command.upgrade(cfg, "0033")
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT INTO users (id, name, password_hash, platform_role, created_at) "
            "VALUES ('owner', 'Owner', 'unused', 'admin', '2026-10-18')"
        )
        db.execute(
            "INSERT INTO campaigns (id, owner_id, name, status, ruleset_id, ruleset_version, "
            "public_intro, difficulty, party_size_recommended, settings, brief, last_seq, content_chain, "
            "created_at, updated_at) VALUES ('game', 'owner', 'Old game', 'active', 'dnd5e', '1', "
            "'Keep intro', 'normal', 4, '{}', '{}', 12, '[]', '2026-10-18', '2026-10-18')"
        )
        db.execute("INSERT INTO campaign_secrets VALUES ('game', '{}', '{\"kept\":true}')")
    command.upgrade(cfg, "0034")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT purpose, status, last_seq, public_intro FROM campaigns").fetchone() == (
            "game",
            "active",
            12,
            "Keep intro",
        )
        assert db.execute("SELECT plot FROM campaign_secrets").fetchone() == ('{"kept":true}',)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    command.downgrade(cfg, "0033")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT plot FROM campaign_secrets").fetchone() == ('{"kept":true}',)


def test_geography_tables_upgrade_and_downgrade_keep_existing_rows(monkeypatch, tmp_path):
    path = tmp_path / "geography.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    cfg = config()
    command.upgrade(cfg, "0034")
    command.upgrade(cfg, "0035")
    with sqlite3.connect(path) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"geography_nodes", "geography_links"} <= tables
    command.downgrade(cfg, "0034")
    with sqlite3.connect(path) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "geography_nodes" not in tables and "author_projects" in tables
