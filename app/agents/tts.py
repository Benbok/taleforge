"""Озвучка реплик мастера через Gemini TTS (модель с аудио-модальностью).

Позволяет озвучивать сгенерированный текст мастера (kind="narration").
Использует отдельный ключ (TTS_GEMINI_API_KEY или TTS_API_KEY) и модель с генерацией аудио
(например, gemini-2.0-flash). Если ключ не задан, сервис выключен (enabled=False)
и не совершает никаких сетевых вызовов.
"""

from __future__ import annotations

import base64
import io
import logging
import re
import wave
from pathlib import Path
from typing import Any

import httpx

from app.core import voice

log = logging.getLogger(__name__)

# Регулярки для очистки текста перед отправкой в TTS
MARKUP_RE = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")
MD_HEADER_RE = re.compile(r"^#+\s*", re.MULTILINE)
MD_FORMAT_RE = re.compile(r"[*_~`]")
SPACE_RE = re.compile(r"\s+")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM_INSTRUCTION = (
    "You are a professional fantasy audio narrator and voice actor. "
    "Read the following story text aloud verbatim in Russian, with appropriate dramatic atmosphere, "
    "clear diction, and natural pacing. Do not add, omit, or alter any words. "
    "Do not reply as a character or player. Only read the provided text exactly as written."
)


def clean_narration_text(raw_text: str) -> str:
    """Удаляет внутреннюю разметку сущностей TaleForge [[id|Текст]] и базовый Markdown."""
    # [[c:hero_1|Эльфийка]] -> Эльфийка
    text = MARKUP_RE.sub(r"\2", raw_text)
    # Заголовки #
    text = MD_HEADER_RE.sub("", text)
    # Звёздочки, подчёркивания, бэктики (*курсив*, **жирный**)
    text = MD_FORMAT_RE.sub("", text)
    # Нормализация пробелов и переносов
    text = SPACE_RE.sub(" ", text).strip()
    return text


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 24000, channels: int = 1, sampwidth: int = 2) -> bytes:
    """Оборачивает «сырой» PCM 16-bit little-endian поток от Gemini в валидный WAV-контейнер."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(sample_rate)
        w.writeframes(pcm_bytes)
    return buf.getvalue()


def wav_duration(wav_bytes: bytes) -> float:
    """Вычисляет длительность WAV файла в секундах."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            if rate > 0:
                return round(frames / float(rate), 1)
    except Exception:
        pass
    return 0.0


class TextToSpeech:
    """Подключаемый сервис синтеза речи мастера на базе Gemini API."""

    def __init__(
        self,
        api_key: str | None,
        model: str = "gemini-3.8-flash-tts",
        voice: str = "Fenrir",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key.strip() if api_key else None
        self.model = model
        self.voice = voice
        self.timeout = timeout
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def synthesize(self, text: str, voice_name: str | None = None) -> tuple[bytes, str, float] | None:
        """Синтезирует речь из текста.

        Возвращает (audio_bytes, mime_type, duration_seconds) или None в случае ошибки.
        """
        if not self.enabled:
            return None

        clean = clean_narration_text(text)
        if not clean:
            return None

        resolved_voice = voice_name or self.voice
        url = f"{GEMINI_API_URL.format(model=self.model)}?key={self.api_key}"
        payload: dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": clean}],
                }
            ],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": resolved_voice,
                        }
                    }
                },
            },
        }
        if not self.model.endswith("-tts"):
            payload["systemInstruction"] = {
                "parts": [{"text": SYSTEM_INSTRUCTION}],
            }

        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                res = await client.post(url, json=payload)
                if res.status_code != 200:
                    log.warning("Gemini TTS ошибка %s: %s", res.status_code, res.text[:500])
                    return None

                data = res.json()
                candidates = data.get("candidates") or []
                if not candidates:
                    log.warning("Gemini TTS: пустой список кандидатов")
                    return None

                parts = candidates[0].get("content", {}).get("parts") or []
                inline_data = next((p.get("inlineData") for p in parts if "inlineData" in p), None)
                if not inline_data or not inline_data.get("data"):
                    log.warning("Gemini TTS: в ответе нет аудио inlineData")
                    return None

                raw_bytes = base64.b64decode(inline_data["data"])
                mime = (inline_data.get("mimeType") or "").strip().lower()

                # Если пришёл сырой PCM, преобразуем в WAV
                if "audio/pcm" in mime or not raw_bytes.startswith(b"RIFF"):
                    # Часто приходит "audio/pcm;rate=24000"
                    rate = 24000
                    rate_match = re.search(r"rate=(\d+)", mime)
                    if rate_match:
                        rate = int(rate_match.group(1))
                    audio_bytes = pcm_to_wav(raw_bytes, sample_rate=rate)
                    duration = round(len(raw_bytes) / (rate * 2), 1)
                    return audio_bytes, "audio/wav", duration
                else:
                    duration = wav_duration(raw_bytes)
                    return raw_bytes, "audio/wav", duration

        except Exception as e:
            log.warning("сбой при вызове Gemini TTS: %s", e)
            return None

    async def voice_for_narration(
        self, media_dir: Path, campaign_id: str, narration_text: str, voice_name: str | None = None
    ) -> dict[str, Any] | None:
        """Синтезирует аудио и сохраняет его в медиа-хранилище кампании.

        Возвращает метаданные для Message.data["voice"] ({"id": voice_id, "duration": seconds})
        или None при сбое или отсутствии настройки.
        """
        if not self.enabled:
            return None

        result = await self.synthesize(narration_text, voice_name=voice_name)
        if not result:
            return None

        audio_bytes, mime, duration = result
        try:
            saved = voice.save(
                media_dir=media_dir,
                campaign_id=campaign_id,
                user_id="master",
                audio=audio_bytes,
                content_type=mime,
            )
            return {"id": saved["id"], "duration": duration}
        except Exception as e:
            log.warning("не удалось сохранить аудиофайл озвучки мастера: %s", e)
            return None
