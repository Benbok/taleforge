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


CAMPAIGN_FLAGS = (
    "audio_enabled",
    "sfx_enabled",
    "scene_generation",
    "scene_generation_llm",
    "location_layouts",
    "location_layouts_llm",
)


def _flags(raw: str) -> tuple[str, ...]:
    names = tuple(x.strip() for x in raw.split(",") if x.strip())
    unknown = [x for x in names if x not in CAMPAIGN_FLAGS]
    if unknown:
        raise ValueError(f"NEW_CAMPAIGN_FLAGS: неизвестные флаги {unknown}; допустимы {', '.join(CAMPAIGN_FLAGS)}")
    return names


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
    # флаги, включённые у новой кампании сразу (NEW_CAMPAIGN_FLAGS через запятую); владелец выключит их в настройках
    new_campaign_flags: tuple[str, ...] = ()
    # SFX inference runs in an isolated process; never imports torch into the web server.
    sfx_enabled: bool = False
    sfx_backend: str = "stable-audio-3"
    sfx_device: str = "cpu"
    sfx_model: str = "small-sfx"
    sfx_model_revision: str = "main"  # first download resolves this to an immutable SHA in the manifest
    sfx_model_dir: Path = ROOT / "models" / "sfx"
    sfx_python: str = ""  # separate Python environment; empty uses this interpreter
    sfx_steps: int = 8
    sfx_threads: int = 2
    sfx_max_queue: int = 16
    sfx_campaign_queue: int = 4
    sfx_timeout_seconds: int = 120
    sfx_cache_max_bytes: int = 512 * 1024 * 1024
    sfx_playback_ttl: int = 15
    sfx_worker_embedded: bool = True  # coordinator only; inference always a subprocess
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
    voicestudio_api_base: str = "http://host.docker.internal:3900/v1"
    voicestudio_api_key: str | None = None
    voicestudio_voice: str = "demo0001"

    # Две модели на провайдера: основная пишет повествование, техническая — парсер, решение хода, сводки, эмоции
    llm_provider: str = "gemini"
    decide_model: str = "technical"  # фаза решения хода (выбор инструментов и бросков): technical или main
    gemini_main_model: str = "gemini-2.5-flash"
    gemini_technical_model: str = "gemini-2.5-flash-lite"
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
            new_campaign_flags=_flags(_env("NEW_CAMPAIGN_FLAGS", "") or ""),
            sfx_enabled=(_env("SFX_ENABLED", "0") or "0").lower() in ("1", "true", "yes"),
            sfx_backend=_env("SFX_BACKEND", cls.sfx_backend),
            sfx_device=_env("SFX_DEVICE", cls.sfx_device),
            sfx_model=_env("SFX_MODEL", cls.sfx_model),
            sfx_model_revision=_env("SFX_MODEL_REVISION", cls.sfx_model_revision),
            sfx_model_dir=Path(_env("SFX_MODEL_DIR", str(ROOT / "models" / "sfx"))),
            sfx_python=_env("SFX_PYTHON", ""),
            sfx_steps=max(1, min(50, int(_env("SFX_STEPS", "8")))),
            sfx_threads=max(1, int(_env("SFX_THREADS", "2"))),
            sfx_max_queue=max(1, int(_env("SFX_MAX_QUEUE", "16"))),
            sfx_campaign_queue=max(1, int(_env("SFX_CAMPAIGN_QUEUE", "4"))),
            sfx_timeout_seconds=max(10, int(_env("SFX_TIMEOUT_SECONDS", "120"))),
            sfx_cache_max_bytes=max(0, int(_env("SFX_CACHE_MAX_BYTES", str(cls.sfx_cache_max_bytes)))),
            sfx_playback_ttl=max(1, min(60, int(_env("SFX_PLAYBACK_TTL", "15")))),
            sfx_worker_embedded=(_env("SFX_WORKER_EMBEDDED", "1") or "1").lower() in ("1", "true", "yes"),
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
            voicestudio_api_base=_env("VOICESTUDIO_API_BASE", cls.voicestudio_api_base),
            voicestudio_api_key=_env("VOICESTUDIO_API_KEY", cls.voicestudio_api_key),
            voicestudio_voice=_env("VOICESTUDIO_VOICE", cls.voicestudio_voice),
            llm_provider=_env("LLM_PROVIDER", cls.llm_provider).lower(),
            decide_model=_env("DECIDE_MODEL", cls.decide_model).lower(),
            gemini_main_model=_env("GEMINI_MAIN_MODEL", cls.gemini_main_model),
            gemini_technical_model=_env("GEMINI_TECHNICAL_MODEL", cls.gemini_technical_model),
            claude_main_model=_env("CLAUDE_MAIN_MODEL", cls.claude_main_model),
            claude_technical_model=_env("CLAUDE_TECHNICAL_MODEL", cls.claude_technical_model),
            local_main_model=_env("LOCAL_MAIN_MODEL", cls.local_main_model),
            local_technical_model=_env("LOCAL_TECHNICAL_MODEL", cls.local_technical_model),
        )


LLM_FIELDS = ("llm_provider", "decide_model") + tuple(
    f"{p}_{kind}_model" for p in ("gemini", "claude", "local") for kind in ("main", "technical")
)


def update_env(key: str, value: str) -> None:
    """Меняет переменную в .env и сразу в работающем сервере (только настройки моделей).

    Объект ``settings`` обновляется на месте: модули держат ссылку на него, новый объект они бы не увидели.
    """
    import re

    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or not re.fullmatch(r"[\w./:-]+", value):
        raise ValueError(f"недопустимое значение для {key}")
    env_path = ROOT / ".env"
    content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    if re.search(rf"^{key}=", content, flags=re.MULTILINE):
        content = re.sub(rf"^{key}=.*$", f"{key}={value}", content, flags=re.MULTILINE)
    else:
        content += ("" if not content or content.endswith("\n") else "\n") + f"{key}={value}\n"
    env_path.write_text(content, encoding="utf-8")
    os.environ[key] = value  # переменные окружения важнее .env в _env: без этого docker вернул бы старое

    global DOTENV
    DOTENV = _load_env_file(env_path)
    fresh = Settings.from_env()
    for name in LLM_FIELDS:  # остальное (секрет JWT, база) на лету не меняем
        object.__setattr__(settings, name, getattr(fresh, name))


settings = Settings.from_env()
