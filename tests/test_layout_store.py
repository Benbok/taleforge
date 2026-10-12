"""Фазы комплекса в механизме подготовки (спецификация 2026-10-12, §8): CHECK, миграция и идемпотентный резерв."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.layout import store
from tests.game import import_base, party, quiet
from tests.layout_pilot import pilot_intent
from tests.test_map import _ok, _play


def test_sqlite_alembic_layout_phases_upgrade_and_downgrade(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    db_path = tmp_path / "phases.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    def table_sql() -> str:
        with sqlite3.connect(db_path) as db:
            return db.execute("SELECT sql FROM sqlite_master WHERE name = 'world_generation_states'").fetchone()[0]

    command.upgrade(config, "0020")
    assert "location_layout" not in table_sql()
    command.upgrade(config, "0021")
    assert "location_layout" in table_sql() and "location_geometry" in table_sql()
    command.downgrade(config, "0020")
    assert "location_layout" not in table_sql() and "container_contents" in table_sql()


def test_reserve_layout_is_idempotent(client, admin, settings):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    quiet(client)
    cid = campaign["id"]

    async def go(ctx):
        temple = (await _ok(ctx, "create_location", {"name": "Старый храм"}))["location_id"]
        root = ctx.world.entities[temple]
        first = await store.reserve_layout(ctx.session, ctx.campaign, root, pilot_intent())
        again = await store.reserve_layout(ctx.session, ctx.campaign, root, pilot_intent())
        assert first.id == again.id and first.phase == "location_layout" and first.requested_at is None
        assert first.reservation["intent"] == pilot_intent().model_dump(mode="json")
        assert first.seed == store.layout_seed(cid, temple) and 0 <= first.seed < 2**31
        assert store.complex_of(root) is None and store.blueprint_of(root) is None
        return first.id

    ref = _play(settings, cid, go)
    assert isinstance(ref, str)
