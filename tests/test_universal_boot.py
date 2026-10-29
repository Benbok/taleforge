"""Real lifespan and migration installation, without metadata.create_all shortcuts."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import login
from tests.universal_helpers import create_hero


def test_fresh_boot_uses_universal_and_restart_keeps_real_library_hero(tmp_path, monkeypatch):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'fresh-install.db'}",
        superadmin_name="root",
        superadmin_password="rootpass",
        voicestudio_api_base="",
    )
    with TestClient(create_app(settings)) as client:
        monkeypatch.setattr(client.app.state.master, "notify", lambda *_: None)
        headers = login(client, "root", "rootpass")
        hero_id = create_hero(client, headers)
        before = client.get(f"/api/me/characters/{hero_id}", headers=headers).json()
        created = client.post(
            "/api/campaigns",
            headers=headers,
            json={
                "name": "Fresh Universal",
                "owner_plays": True,
                "master": {"type": "owner"},
                "tts_enabled": False,
            },
        )
        assert created.status_code == 201, created.text
        campaign_id = created.json()["id"]
        assert created.json()["ruleset_id"] == "universal"
        assert created.json()["ruleset_version"] == "universal.v1"
    with TestClient(create_app(settings)) as client:
        headers = login(client, "root", "rootpass")
        assert client.get(f"/api/me/characters/{hero_id}", headers=headers).json() == before
        assert client.get(f"/api/campaigns/{campaign_id}", headers=headers).json()["ruleset_id"] == "universal"
    with sqlite3.connect(tmp_path / "fresh-install.db") as connection:
        assert connection.execute("select version_num from alembic_version").fetchone() == ("universal_0017",)
        assert connection.execute("select count(*) from equipment_artworks").fetchone() == (0,)


def test_incompatible_database_remains_untouched_by_real_startup(tmp_path):
    path = tmp_path / "incompatible.db"
    with sqlite3.connect(path) as connection:
        connection.execute("create table old_heroes (id integer primary key, name text)")
        connection.execute("insert into old_heroes values (1, 'Preserve me')")
    settings = Settings(database_url=f"sqlite+aiosqlite:///{path}", voicestudio_api_base="")
    with pytest.raises(RuntimeError, match="universal database"):
        with TestClient(create_app(settings)):
            pass
    with sqlite3.connect(path) as connection:
        assert connection.execute("select * from old_heroes").fetchall() == [(1, "Preserve me")]
        assert connection.execute("select name from sqlite_master where type='table'").fetchall() == [("old_heroes",)]
