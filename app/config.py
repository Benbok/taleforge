"""Настройки из переменных окружения. Ключи и секреты живут только здесь, не в коде и не в БД."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite+aiosqlite:///./taleforge.db"
    redis_url: str | None = None
    jwt_secret: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    jwt_ttl_hours: int = 24 * 30
    public_url: str = "http://localhost:8000"
    superadmin_name: str | None = None
    superadmin_password: str | None = None
    content_dir: Path = ROOT / "content"
    ws_auth_timeout_sec: float = 10.0
    message_max_len: int = 4000
    history_on_join: int = 50
    open_signup: bool = True  # регистрация игрока без приглашения; кампании он всё равно видит только по приглашению
    # Журнал мастера показывает скрытые броски и шёпот. Выключите — останется только факт такого действия
    master_log_secrets: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        secret = _env("JWT_SECRET")
        if secret is None:
            # Без заданного секрета токены живут до перезапуска сервера. Для игры с друзьями задайте JWT_SECRET.
            secret = secrets.token_urlsafe(32)
        return cls(
            database_url=_env("DATABASE_URL", cls.database_url),
            redis_url=_env("REDIS_URL"),
            jwt_secret=secret,
            jwt_ttl_hours=int(_env("JWT_TTL_HOURS", str(cls.jwt_ttl_hours))),
            public_url=_env("PUBLIC_URL", cls.public_url).rstrip("/"),
            superadmin_name=_env("SUPERADMIN_NAME"),
            superadmin_password=_env("SUPERADMIN_PASSWORD"),
            content_dir=Path(_env("CONTENT_DIR", str(ROOT / "content"))),
            open_signup=(_env("OPEN_SIGNUP", "1") or "1").lower() not in ("0", "false", "no"),
            master_log_secrets=(_env("MASTER_LOG_SECRETS", "1") or "1").lower() not in ("0", "false", "no"),
        )
