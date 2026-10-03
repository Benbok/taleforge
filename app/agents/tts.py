import abc
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

# Регулярки для очистки текста
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
    text = MARKUP_RE.sub(r"\2", raw_text)
    text = MD_HEADER_RE.sub("", text)
    text = MD_FORMAT_RE.sub("", text)
    text = SPACE_RE.sub(" ", text).strip()
    return text


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 24000, channels: int = 1, sampwidth: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(sample_rate)
        w.writeframes(pcm_bytes)
    return buf.getvalue()


def wav_duration(wav_bytes: bytes) -> float:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            if rate > 0:
                return round(frames / float(rate), 1)
    except Exception:
        pass
    return 0.0


class TTSEngine(abc.ABC):
    """Базовый класс для всех TTS-провайдеров."""

    @property
    @abc.abstractmethod
    def enabled(self) -> bool:
        pass

    @abc.abstractmethod
    async def synthesize(self, text: str, voice_name: str | None = None) -> tuple[bytes, str, float] | None:
        """Синтезирует речь из текста.
        Возвращает (audio_bytes, mime_type, duration_seconds) или None в случае ошибки.
        """
        pass

    async def voice_for_narration(
        self, media_dir: Path, campaign_id: str, narration_text: str, voice_name: str | None = None
    ) -> dict[str, Any] | None:
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
            log.warning("не удалось сохранить аудиофайл озвучки Мастера: %s", e)
            return None


class GeminiTTS(TTSEngine):
    def __init__(
        self,
        api_key: str | None,
        model: str = "gemini-3.8-flash-tts",
        voice: str = "Fenrir",
        timeout: float = 120.0,
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
        clean = clean_narration_text(text)
        if not clean:
            return None

        resolved_voice = voice_name or self.voice
        url = f"{GEMINI_API_URL.format(model=self.model)}?key={self.api_key}"
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": clean}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": resolved_voice}
                    }
                },
            },
        }
        if not self.model.endswith("-tts"):
            payload["systemInstruction"] = {"parts": [{"text": SYSTEM_INSTRUCTION}]}

        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                res = await client.post(url, json=payload)
                if res.status_code != 200:
                    log.warning("Gemini TTS ошибка %s: %s", res.status_code, res.text[:500])
                    return None

                data = res.json()
                candidates = data.get("candidates") or []
                if not candidates:
                    return None

                parts = candidates[0].get("content", {}).get("parts") or []
                inline_data = next((p.get("inlineData") for p in parts if "inlineData" in p), None)
                if not inline_data or not inline_data.get("data"):
                    return None

                raw_bytes = base64.b64decode(inline_data["data"])
                mime = (inline_data.get("mimeType") or "").strip().lower()

                if "audio/pcm" in mime or not raw_bytes.startswith(b"RIFF"):
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



class VoiceStudioTTS(TTSEngine):
    """OpenAI-compatible TTS engine for Voice Studio with dynamic profile resolution."""

    def __init__(
        self,
        api_base: str = "http://host.docker.internal:3900/v1",
        api_key: str | None = None,
        voice: str = "demo0001",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.voice = voice
        self.timeout = timeout
        self._transport = transport
        self._profiles_cache: dict[str, dict[str, Any]] = {}
        self._profiles_cache_time: float = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.api_base)

    async def _get_profile(self, voice_id: str) -> dict[str, Any] | None:
        """Fetch and cache profile metadata from Voice Studio to dynamically apply language, seed, etc."""
        import time
        now = time.time()
        if not self._profiles_cache or (now - self._profiles_cache_time) > 60.0:
            profiles_url = f"{self.api_base.rsplit('/v1', 1)[0]}/profiles"
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            try:
                async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
                    resp = await client.get(profiles_url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, list):
                            self._profiles_cache = {
                                str(p.get("id")): p
                                for p in data
                                if isinstance(p, dict) and p.get("id")
                            }
                            self._profiles_cache_time = now
            except Exception as e:
                log.debug("Не удалось обновить профили Voice Studio: %s", e)
        return self._profiles_cache.get(voice_id)

    async def synthesize(self, text: str, voice_name: str | None = None) -> tuple[bytes, str, float] | None:
        clean = clean_narration_text(text)
        if not clean:
            return None

        resolved_voice = voice_name or self.voice
        url = f"{self.api_base}/audio/speech"
        
        payload: dict[str, Any] = {
            "model": "tts-1",
            "input": clean,
            "voice": resolved_voice,
            "response_format": "wav",
        }

        # Динамически подтягиваем настройки профиля из Voice Studio без хардкода
        profile = await self._get_profile(resolved_voice)
        if profile:
            lang = profile.get("language")
            if lang and str(lang).lower() != "auto":
                payload["language"] = lang
            else:
                payload["language"] = "Russian"

            if profile.get("seed") is not None:
                payload["seed"] = profile["seed"]
        else:
            payload["language"] = "Russian"

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code != 200:
                    log.warning("Voice Studio TTS error %s: %s", res.status_code, res.text[:500])
                    return None
                
                duration = max(0.1, len(res.content) / 32000.0)
                return res.content, "audio/wav", duration
        except Exception as e:
            log.exception("Failed to connect to Voice Studio TTS: %s", e)
            return None


class DisabledTTS(TTSEngine):
    @property
    def enabled(self) -> bool:
        return False
        
    async def synthesize(self, text: str, voice_name: str | None = None) -> tuple[bytes, str, float] | None:
        return None



class TTSManager:
    def __init__(self, settings):
        self.engines = {
            "gemini": GeminiTTS(api_key=settings.gemini_tts_api_key, model=settings.gemini_tts_model, voice=settings.gemini_tts_voice),
            "voicestudio": VoiceStudioTTS(api_base=settings.voicestudio_api_base, api_key=settings.voicestudio_api_key, voice=settings.voicestudio_voice),
        }
        self.default_provider = settings.tts_provider

    def get_engine(self, provider: str | None = None) -> TTSEngine:
        p = provider or self.default_provider
        return self.engines.get(p) or self.engines["gemini"]

    async def voice_for_narration(
        self, media_dir, campaign_id: str, narration_text: str, provider: str | None = None, voice_name: str | None = None
    ):
        engine = self.get_engine(provider)
        if not engine.enabled:
            return None
        if provider and provider not in ("gemini", "voicestudio"):
            voice_name = None
        return await engine.voice_for_narration(media_dir, campaign_id, narration_text, voice_name)

