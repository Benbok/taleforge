from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import Settings


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


class SfxInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    description: str | None = Field(default=None, min_length=8, max_length=300)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    duration_seconds: float = Field(default=3, ge=1, le=4, allow_inf_nan=False)
    context: str = Field(default="", max_length=200)
    urgency: Literal["scene", "ambient"] = "scene"
    sound_id: str | None = Field(default=None, pattern=r"^sf_[a-f0-9]{16}$")

    @model_validator(mode="after")
    def need_description(self):
        if not self.sound_id and (not self.description or len(normalize(self.description)) < 8):
            raise ValueError("нужны описание звука (8–300 символов) или sound_id сохранённого эффекта")
        return self


def parameters(a: SfxInput, settings: Settings) -> dict:
    manifest = settings.sfx_model_dir / "manifest.json"
    digest = "unprepared"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("revision") == settings.sfx_model_revision:
                digest = data["resolved_revision"]
        except (OSError, ValueError, KeyError):
            pass
    return {
        "description": normalize(a.description or ""),
        "context": normalize(a.context),
        "duration_seconds": float(a.duration_seconds),
        "backend": settings.sfx_backend,
        "model": settings.sfx_model,
        "revision": settings.sfx_model_revision,
        "weights_digest": digest,
        "device": settings.sfx_device,
        "steps": settings.sfx_steps,
        "seed": 0,
        "pipeline": "opus-peak-v1",
    }


def cache_key(a: SfxInput, settings: Settings) -> str:
    return parameters_key(parameters(a, settings))


def parameters_key(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
