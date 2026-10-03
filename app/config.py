"""Настройки из переменных окружения. Ключи и секреты живут только здесь, не в коде и не в БД."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("'\"")
    return out


DOTENV = _load_env_file(ROOT / ".env")


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name) or DOTENV.get(name)
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
    media_dir: Path = ROOT / "media"  # голосовые реплики игроков
    audio_dir: Path = ROOT / "audio"  # библиотека звука: треки и tracks.yaml (design/audio-mixer.md)
    ws_auth_timeout_sec: float = 10.0
    message_max_len: int = 4000
    history_on_join: int = 50
    open_signup: bool = True  # регистрация игрока без приглашения; кампании он всё равно видит только по приглашению
    # Журнал мастера показывает скрытые броски и шёпот. Выключите — останется только факт такого действия
    master_log_secrets: bool = True
    # Голосовой ввод: локальный сервер расшифровки (Speaches, whisper.cpp). Без адреса кнопки микрофона нет
    stt_api_base: str | None = None
    stt_model: str = "deepdml/faster-whisper-large-v3-turbo-ct2"
    stt_language: str = "ru"
    stt_concurrency: int = 1
    # Озвучка текста мастера
    tts_provider: str = "gemini"  # gemini, silero, none
    gemini_tts_api_key: str | None = None
    gemini_tts_model: str = "gemini-3.8-flash-tts"
    gemini_tts_voice: str = "Fenrir"  # Puck, Charon, Kore, Fenrir, Aoede
    silero_api_base: str = "http://localhost:8001"
    silero_voice: str = "aidar"
    xtts_api_base: str = "http://localhost:8020"
    xtts_voice: str = "echo.wav"

    llm_provider: str = "claude"
    gemini_main_model: str = "gemini-2.5-pro"
    gemini_technical_model: str = "gemini-3.5-flash-lite"
    claude_main_model: str = "anthropic/claude-opus-5"
    claude_technical_model: str = "anthropic/claude-haiku-4-5"
    local_main_model: str = "qwen2.5-14b"
    local_technical_model: str = "qwen2.5-7b"

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
            media_dir=Path(_env("MEDIA_DIR", str(ROOT / "media"))),
            audio_dir=Path(_env("AUDIO_DIR", str(ROOT / "audio"))),
            open_signup=(_env("OPEN_SIGNUP", "1") or "1").lower() not in ("0", "false", "no"),
            master_log_secrets=(_env("MASTER_LOG_SECRETS", "1") or "1").lower() not in ("0", "false", "no"),
            stt_api_base=_env("STT_API_BASE"),
            stt_model=_env("STT_MODEL", cls.stt_model),
            stt_language=_env("STT_LANGUAGE", cls.stt_language),
            stt_concurrency=int(_env("STT_CONCURRENCY", str(cls.stt_concurrency))),
            tts_provider=_env("TTS_PROVIDER", cls.tts_provider).lower(),
            gemini_tts_api_key=_env("GEMINI_TTS_API_KEY") or _env("GEMINI_API_KEY"),
            gemini_tts_model=_env("GEMINI_TTS_MODEL", cls.gemini_tts_model),
            gemini_tts_voice=_env("GEMINI_TTS_VOICE", cls.gemini_tts_voice),
            silero_api_base=_env("SILERO_API_BASE", cls.silero_api_base),
            silero_voice=_env("SILERO_VOICE", cls.silero_voice),
            xtts_api_base=_env("XTTS_API_BASE", cls.xtts_api_base),
            xtts_voice=_env("XTTS_VOICE", cls.xtts_voice),
            llm_provider=_env("LLM_PROVIDER", cls.llm_provider).lower(),
            gemini_main_model=_env("GEMINI_MAIN_MODEL", cls.gemini_main_model),
            gemini_technical_model=_env("GEMINI_TECHNICAL_MODEL", cls.gemini_technical_model),
            claude_main_model=_env("CLAUDE_MAIN_MODEL", cls.claude_main_model),
            claude_technical_model=_env("CLAUDE_TECHNICAL_MODEL", cls.claude_technical_model),
            local_main_model=_env("LOCAL_MAIN_MODEL", cls.local_main_model),
            local_technical_model=_env("LOCAL_TECHNICAL_MODEL", cls.local_technical_model),
        )

def update_env(key: str, value: str):
    import re
    env_path = ROOT / ".env"
    if not env_path.exists():
        env_path.write_text(f"{key}={value}\n", encoding="utf-8")
    else:
        content = env_path.read_text(encoding="utf-8")
        if re.search(rf"^{key}=", content, flags=re.MULTILINE):
            content = re.sub(rf"^{key}=.*$", f"{key}={value}", content, flags=re.MULTILINE)
        else:
            if not content.endswith("\n"):
                content += "\n"
            content += f"{key}={value}\n"
        env_path.write_text(content, encoding="utf-8")
    
    # Reload DOTENV and settings dynamically
    global DOTENV, settings
    DOTENV = _load_env_file(ROOT / ".env")
    settings = Settings.from_env()

settings = Settings.from_env()


