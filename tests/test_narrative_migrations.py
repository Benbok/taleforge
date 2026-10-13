"""Migration tests for narrative foundation schema (0021)."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_sqlite_alembic_narrative_foundation_upgrade_and_downgrade(monkeypatch, tmp_path):
    """Verify upgrade 0020 -> 0021 and downgrade 0021 -> 0020 on clean SQLite database."""
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    db_path = tmp_path / "narrative_mig.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    # 1. Migrate to 0020 base
    command.upgrade(config, "0020")
    with sqlite3.connect(db_path) as db:
        tables_before = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert not {"narrative_states", "narrative_facts", "narrative_threads"} & tables_before

    # 2. Upgrade to 0021 (head)
    command.upgrade(config, "0021")
    with sqlite3.connect(db_path) as db:
        tables_after = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"narrative_states", "narrative_facts", "narrative_threads"} <= tables_after

        # Verify fact indices
        indices = {row[1] for row in db.execute("PRAGMA index_list(narrative_facts)")}
        assert "ix_narrative_facts_subject" in indices
        assert "ix_narrative_facts_campaign_id" in indices

    # 3. Downgrade back to 0020
    command.downgrade(config, "0020")
    with sqlite3.connect(db_path) as db:
        tables_downgraded = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert not {"narrative_states", "narrative_facts", "narrative_threads"} & tables_downgraded

    # 4. Upgrade to 0022 (head)
    command.upgrade(config, "0022")
    with sqlite3.connect(db_path) as db:
        tables_0022 = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "narrative_work" in tables_0022

        indices = {row[1] for row in db.execute("PRAGMA index_list(narrative_work)")}
        assert "ix_narrative_work_status" in indices
        assert "ix_narrative_work_campaign_created" in indices
        assert "ix_narrative_work_capacity_slot" in indices
        assert "ix_narrative_work_campaign_preparing" in indices

    # 5. Downgrade back to 0021
    command.downgrade(config, "0021")
    with sqlite3.connect(db_path) as db:
        tables_down_0021 = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "narrative_work" not in tables_down_0021
        assert {"narrative_states", "narrative_facts", "narrative_threads"} <= tables_down_0021

    # 6. Re-upgrade to 0022 (head)
    command.upgrade(config, "0022")
    with sqlite3.connect(db_path) as db:
        tables_head = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "narrative_work" in tables_head
