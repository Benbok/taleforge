import sqlite3
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.config import Config

from app.core.map_memory import static_snapshot


def test_snapshot_is_personal_and_excludes_entities():
    place = SimpleNamespace(
        id="road",
        name="Дорога",
        kind="location",
        campaign_id="camp",
        state={
            "complex": {"root_id": "root"},
            "sketch": {
                "shape": "room",
                "cols": 3,
                "rows": 3,
                "party": [1, 1],
                "walls": [[0, 0]],
                "exits": [{"name": "Склеп", "passage_ref": "vault", "side": "e", "at": 1}],
                "features": [
                    {"name": "Колонна", "kind": "column", "cells": [[1, 1]]},
                    {"entity_id": "chest", "name": "Сундук", "kind": "object", "cells": [[2, 2]]},
                ],
            },
        },
    )
    root = SimpleNamespace(id="root", state={"blueprint": {"revision": 2}})
    snapshot = static_snapshot(
        place,
        root,
        root.state["blueprint"],
        {"chest": SimpleNamespace(id="chest", kind="object")},
        discovered_passages=frozenset({("root", "vault")}),
        revealed=frozenset(),
    )
    assert snapshot["schema_version"] == 1
    assert all("entity_id" not in feature for feature in snapshot["geometry"]["features"])
    assert "tokens" not in snapshot
    assert snapshot["geometry"]["exits"][0]["passage_ref"] == "vault"


def test_map_memory_sqlite_upgrade_downgrade(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    db_path = tmp_path / "map-memory.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    command.upgrade(config, "0025")
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='map_memories'").fetchone()
    command.downgrade(config, "0024")
    with sqlite3.connect(db_path) as db:
        assert (
            db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='map_memories'").fetchone() is None
        )
