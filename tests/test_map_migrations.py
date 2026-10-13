"""The merged migration chain must produce the ORM schema on both databases."""

from pathlib import Path

from alembic import command
from alembic.config import Config


def test_location_map_migrations_match_metadata(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'map-migrations.db'}")

    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "0023")
    command.upgrade(config, "head")
    command.check(config)
