"""Тема кабинета и пользовательские настройки музыки."""

import dataclasses
import hashlib
import math
import sqlite3

import pytest
import yaml
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.schemas import MenuMusicPreferencesPatch
from app.core import menu_music
from app.main import create_app
from tests.conftest import login


def _client(settings, tmp_path):
    root = tmp_path / "audio"
    root.mkdir()
    (root / "scene.ogg").write_bytes(b"OggS-scene")
    (root / "tracks.yaml").write_text(
        yaml.safe_dump(
            [{"id": "scene", "file": "scene.ogg", "layer": "music", "title": "Сцена", "moods": ["calm"]}],
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    configured = dataclasses.replace(settings, audio_dir=root)
    return TestClient(create_app(configured))


def test_menu_theme_accessible_without_login_but_patch_requires_login(settings, tmp_path):
    with _client(settings, tmp_path) as client:
        # Публичные эндпоинты для страницы логина
        assert client.get("/api/menu-music").status_code == 200
        # Настройки пользователя требуют авторизации
        assert client.patch("/api/me/menu-music", json={}).status_code == 401


def test_menu_theme_is_not_in_scene_library(settings, tmp_path):
    with _client(settings, tmp_path) as client:
        headers = login(client, "root", "rootpass")
        library = client.app.state.audio
        assert all(t.id != "menu_edge_of_the_world" for t in library.all())
        assert "edge_of_the_world.mp3" not in library.unsorted()
        assert all(t.id != "menu_edge_of_the_world" for t in library.for_pack(None))
        assert client.get("/api/menu-music", headers=headers).status_code == 200


def test_missing_menu_theme(settings, tmp_path):
    with _client(settings, tmp_path) as client:
        headers = login(client, "root", "rootpass")
        assert client.get("/api/menu-music", headers=headers).json() is None
        assert client.get("/api/menu-music/file", headers=headers).status_code == 404


def test_menu_preferences_defaults_and_partial_patch(client):
    headers = login(client, "one", "secret1") if False else None
    # The normal test client has the bootstrap account; create an isolated player through signup.
    r = client.post("/api/auth/signup", json={"name": "one", "password": "secret1"})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    assert r.json()["user"]["menu_music"] == {"enabled": True, "volume": 0.2}
    assert client.get("/api/auth/me", headers=headers).json()["menu_music"] == {"enabled": True, "volume": 0.2}
    assert client.patch("/api/me/menu-music", json={"enabled": False}, headers=headers).json() == {
        "enabled": False,
        "volume": 0.2,
    }
    assert client.patch("/api/me/menu-music", json={"volume": 0}, headers=headers).json() == {
        "enabled": False,
        "volume": 0,
    }
    assert client.patch("/api/me/menu-music", json={}, headers=headers).json() == {"enabled": False, "volume": 0}


def test_menu_preferences_are_per_user(client):
    first = client.post("/api/auth/signup", json={"name": "first", "password": "secret1"}).json()
    second = client.post("/api/auth/signup", json={"name": "second", "password": "secret1"}).json()
    h1 = {"Authorization": f"Bearer {first['token']}"}
    h2 = {"Authorization": f"Bearer {second['token']}"}
    assert client.patch("/api/me/menu-music", json={"enabled": False, "volume": 0.5}, headers=h1).status_code == 200
    assert client.get("/api/auth/me", headers=h2).json()["menu_music"] == {"enabled": True, "volume": 0.2}
    assert client.get("/api/auth/me", headers=h1).json()["menu_music"] == {"enabled": False, "volume": 0.5}


@pytest.mark.parametrize(
    "payload",
    [
        {"enabled": None},
        {"enabled": "true"},
        {"volume": None},
        {"volume": -0.1},
        {"volume": 1.1},
        {"volume": "0.2"},
        {"unknown": True},
    ],
)
def test_menu_preferences_invalid_values(client, payload):
    r = client.post("/api/auth/signup", json={"name": f"bad{abs(hash(str(payload)))}", "password": "secret1"})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.patch("/api/me/menu-music", json=payload, headers=headers).status_code == 422


def test_menu_preferences_reject_non_finite_values(client):
    with pytest.raises(ValidationError):
        MenuMusicPreferencesPatch.model_validate({"volume": math.nan})
    with pytest.raises(ValidationError):
        MenuMusicPreferencesPatch.model_validate({"volume": math.inf})
    r = client.post("/api/auth/signup", json={"name": "finite", "password": "secret1"})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    for value in ("NaN", "Infinity", "-Infinity"):
        assert (
            client.patch(
                "/api/me/menu-music",
                content=(f'{{"volume": {value}}}').encode(),
                headers={**headers, "Content-Type": "application/json"},
            ).status_code
            == 422
        )


def test_theme_metadata_and_hash(tmp_path):
    root = tmp_path / "audio"
    path = root / "menu" / "edge_of_the_world.mp3"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"theme")
    track = menu_music.theme_track(root)
    assert track and track["id"] == "menu_edge_of_the_world"
    assert track["title"] == "Edge of the World"
    assert track["layer"] == "music"
    assert track["gain_db"] == 0
    assert track["url"].startswith("/api/menu-music/file?v=")
    assert hashlib.sha256(path.read_bytes()).hexdigest()


def test_menu_music_migration_is_reversible_for_existing_user(tmp_path, monkeypatch):
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    db_path = tmp_path / "menu_music_migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    command.upgrade(config, "0022")
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO users (id, name, password_hash, platform_role, created_at) "
            "VALUES ('u_old', 'old', 'hash', 'player', '2026-01-01 00:00:00')"
        )
        db.commit()
    command.upgrade(config, "0023")
    with sqlite3.connect(db_path) as db:
        row = db.execute("SELECT menu_music_enabled, menu_music_volume FROM users WHERE id = 'u_old'").fetchone()
        assert row == (1, 0.2)
    command.downgrade(config, "0022")
    with sqlite3.connect(db_path) as db:
        assert {row[1] for row in db.execute("PRAGMA table_info(users)")} >= {
            "id",
            "name",
            "password_hash",
            "platform_role",
            "created_at",
        }
        assert "menu_music_enabled" not in {row[1] for row in db.execute("PRAGMA table_info(users)")}
    command.upgrade(config, "0023")
