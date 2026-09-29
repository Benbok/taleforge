"""Голосовой ввод: расшифровка речи локальной моделью Whisper.

Сервер расшифровки — любой OpenAI-совместимый ``POST /audio/transcriptions`` (Speaches, whisper.cpp server),
обычно на той же машине, что и игра. Звук в облако не уходит. Адрес и модель — в окружении сервера
(STT_API_BASE, STT_MODEL); без адреса голосовой ввод выключен и кнопки микрофона нет.

Одна видеокарта считает одну запись за раз, поэтому запросы встают в очередь (STT_CONCURRENCY, по умолчанию 1):
короткая реплика расшифровывается примерно за секунду, и ожидание в очереди остаётся коротким.
"""

from __future__ import annotations

import asyncio
import io
import time
import wave
from datetime import UTC, datetime
from typing import Any

import httpx

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # около 10 минут сжатого звука: реплика столько не длится
TIMEOUT_SEC = 120.0


class STTError(Exception):
    """Причина сбоя по-русски: клиент показывает её у кнопки микрофона как есть."""


def _silence_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


class SpeechToText:
    def __init__(
        self,
        api_base: str | None,
        model: str,
        language: str = "ru",
        concurrency: int = 1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/") if api_base else None
        self.model = model
        self.language = language
        self._slots = asyncio.Semaphore(max(1, concurrency))
        self._transport = transport  # подменяется в тестах
        self.waiting = 0  # запросов в очереди прямо сейчас, включая выполняемые
        self.last_check: dict[str, Any] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_base)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "api_base": self.api_base,
            "model": self.model,
            "language": self.language,
            "queue": self.waiting,
            "last_check": self.last_check,
        }

    async def transcribe(self, audio: bytes, content_type: str | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise STTError("голосовой ввод выключен: на сервере не задан адрес расшифровки STT_API_BASE")
        if not audio:
            raise STTError("пустая запись: микрофон ничего не передал")
        if len(audio) > MAX_AUDIO_BYTES:
            raise STTError("запись слишком длинная: разбейте реплику на части")
        ctype = (content_type or "audio/webm").split(";", 1)[0].strip()
        ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/wav": "wav", "audio/mpeg": "mp3"}
        filename = f"speech.{ext.get(ctype, 'webm')}"
        queued_at = time.monotonic()
        self.waiting += 1
        try:
            async with self._slots:
                started = time.monotonic()
                text = await self._post(audio, filename, ctype)
                done = time.monotonic()
        finally:
            self.waiting -= 1
        return {
            "text": text.strip(),
            "queued_ms": int((started - queued_at) * 1000),
            "took_ms": int((done - started) * 1000),
        }

    async def _post(self, audio: bytes, filename: str, ctype: str) -> str:
        url = f"{self.api_base}/audio/transcriptions"
        data = {"model": self.model, "response_format": "json"}
        if self.language:
            data["language"] = self.language
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SEC, transport=self._transport) as client:
                resp = await client.post(url, data=data, files={"file": (filename, audio, ctype)})
        except httpx.TimeoutException as e:
            raise STTError(f"сервер расшифровки не ответил за {int(TIMEOUT_SEC)} с") from e
        except httpx.HTTPError as e:
            raise STTError(
                f"сервер расшифровки по адресу {self.api_base} не отвечает: он запущен? ({type(e).__name__})"
            ) from e
        if resp.status_code == 404:
            raise STTError(f"сервер расшифровки не знает модель {self.model} или адрес {url} неверный")
        if resp.status_code >= 400:
            raise STTError(f"сервер расшифровки вернул ошибку {resp.status_code}: {resp.text[:200]}")
        try:
            body = resp.json()
        except ValueError as e:
            raise STTError("сервер расшифровки ответил не JSON: это точно OpenAI-совместимый адрес /v1?") from e
        text = body.get("text") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise STTError("в ответе сервера расшифровки нет текста")
        return text

    async def check(self) -> dict[str, Any]:
        """Секунда тишины на расшифровку: отвечает ли сервер и за сколько. Пишется в last_check для админки."""
        at = datetime.now(UTC).isoformat()
        try:
            r = await self.transcribe(_silence_wav(), "audio/wav")
            result = {"ok": True, "at": at, "latency_ms": r["took_ms"], "queued_ms": r["queued_ms"]}
        except STTError as e:
            result = {"ok": False, "at": at, "error": str(e)}
        self.last_check = result
        return result
