"""Фиксированная тема личного кабинета, не входящая в каталог музыки сцен."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

THEME_ID = "menu_edge_of_the_world"
THEME_TITLE = "Edge of the World"
THEME_FILENAME = "edge_of_the_world.mp3"


def theme_path(audio_dir: Path) -> Path:
    """Вернуть единственный разрешённый путь к теме относительно AUDIO_DIR."""
    return Path(audio_dir) / "menu" / THEME_FILENAME


def theme_track(audio_dir: Path) -> dict[str, Any] | None:
    path = theme_path(audio_dir)
    if not path.is_file():
        return None
    stat = path.stat()
    version = hashlib.sha1(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()[:10]
    return {
        "id": THEME_ID,
        "title": THEME_TITLE,
        "layer": "music",
        "url": f"/api/menu-music/file?v={version}",
        "gain_db": 0.0,
    }
