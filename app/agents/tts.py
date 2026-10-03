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

# Р В Р ВµР С–РЎС“Р В»РЎРЏРЎР‚Р С”Р С‘ Р Т‘Р В»РЎРЏ Р С•РЎвЂЎР С‘РЎРѓРЎвЂљР С”Р С‘ РЎвЂљР ВµР С”РЎРѓРЎвЂљР В°
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
    """Р вЂР В°Р В·Р С•Р Р†РЎвЂ№Р в„– Р С”Р В»Р В°РЎРѓРЎРѓ Р Т‘Р В»РЎРЏ Р Р†РЎРѓР ВµРЎвЂ¦ TTS-Р С—РЎР‚Р С•Р Р†Р В°Р в„–Р Т‘Р ВµРЎР‚Р С•Р Р†."""

    @property
    @abc.abstractmethod
    def enabled(self) -> bool:
        pass

    @abc.abstractmethod
    async def synthesize(self, text: str, voice_name: str | None = None) -> tuple[bytes, str, float] | None:
        """Р РЋР С‘Р Р…РЎвЂљР ВµР В·Р С‘РЎР‚РЎС“Р ВµРЎвЂљ РЎР‚Р ВµРЎвЂЎРЎРЉ Р С‘Р В· РЎвЂљР ВµР С”РЎРѓРЎвЂљР В°.
        Р вЂ™Р С•Р В·Р Р†РЎР‚Р В°РЎвЂ°Р В°Р ВµРЎвЂљ (audio_bytes, mime_type, duration_seconds) Р С‘Р В»Р С‘ None Р Р† РЎРѓР В»РЎС“РЎвЂЎР В°Р Вµ Р С•РЎв‚¬Р С‘Р В±Р С”Р С‘.
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
            log.warning("Р Р…Р Вµ РЎС“Р Т‘Р В°Р В»Р С•РЎРѓРЎРЉ РЎРѓР С•РЎвЂ¦РЎР‚Р В°Р Р…Р С‘РЎвЂљРЎРЉ Р В°РЎС“Р Т‘Р С‘Р С•РЎвЂћР В°Р в„–Р В» Р С•Р В·Р Р†РЎС“РЎвЂЎР С”Р С‘ Р СР В°РЎРѓРЎвЂљР ВµРЎР‚Р В°: %s", e)
            return None


class GeminiTTS(TTSEngine):
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
                    log.warning("Gemini TTS Р С•РЎв‚¬Р С‘Р В±Р С”Р В° %s: %s", res.status_code, res.text[:500])
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
            log.warning("РЎРѓР В±Р С•Р в„– Р С—РЎР‚Р С‘ Р Р†РЎвЂ№Р В·Р С•Р Р†Р Вµ Gemini TTS: %s", e)
            return None


class SileroTTS(TTSEngine):
    """Р ВР Р…РЎвЂљР ВµР С–РЎР‚Р В°РЎвЂ Р С‘РЎРЏ РЎРѓ Р В»Р С•Р С”Р В°Р В»РЎРЉР Р…РЎвЂ№Р С Silero TTS (РЎвЂЎР ВµРЎР‚Р ВµР В· silero-api-server)."""

    def __init__(
        self,
        api_base: str = "http://localhost:8001",
        voice: str = "xenia",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.voice = voice
        self.timeout = timeout
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.api_base)

    async def synthesize(self, text: str, voice_name: str | None = None) -> tuple[bytes, str, float] | None:
        clean = clean_narration_text(text)
        if not clean:
            return None

        resolved_voice = voice_name or self.voice
        # Р Р€ Р В±Р С•Р В»РЎРЉРЎв‚¬Р С‘Р Р…РЎРѓРЎвЂљР Р†Р В° Р С•Р В±Р ВµРЎР‚РЎвЂљР С•Р С” Silero РЎРЊР Р…Р Т‘Р С—Р С•Р С‘Р Р…РЎвЂљ Р С–Р ВµР Р…Р ВµРЎР‚Р В°РЎвЂ Р С‘Р С‘ Р Р…Р В°РЎвЂ¦Р С•Р Т‘Р С‘РЎвЂљРЎРѓРЎРЏ Р С—Р С• Р С—РЎС“РЎвЂљР С‘ /tts/generate
        url = f"{self.api_base}/generate"
        
        payload = {
            "text": clean,
            "speaker": resolved_voice
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                # Р С›РЎвЂљР С—РЎР‚Р В°Р Р†Р В»РЎРЏР ВµР С POST Р В·Р В°Р С—РЎР‚Р С•РЎРѓ. Р вЂР С•Р В»РЎРЉРЎв‚¬Р С‘Р Р…РЎРѓРЎвЂљР Р†Р С• РЎРѓР ВµРЎР‚Р Р†Р ВµРЎР‚Р С•Р Р† (Р Р†Р С”Р В». twirapp Р С‘ ouoertheo) Р Р†Р С•Р В·Р Р†РЎР‚Р В°РЎвЂ°Р В°РЎР‹РЎвЂљ Р В°РЎС“Р Т‘Р С‘Р С•
                res = await client.post(url, json=payload)
                if res.status_code != 200:
                    # Р СџР С•Р С—РЎР‚Р С•Р В±РЎС“Р ВµР С GET, Р ВµРЎРѓР В»Р С‘ POST Р Р…Р Вµ Р С—РЎР‚Р С•РЎв‚¬Р ВµР В»
                    res = await client.get(url, params=payload)
                    if res.status_code != 200:
                        log.warning("Silero TTS Р С•РЎв‚¬Р С‘Р В±Р С”Р В° %s: %s", res.status_code, res.text[:500])
                        return None
                
                audio_bytes = res.content
                duration = wav_duration(audio_bytes)
                return audio_bytes, "audio/wav", duration
        except Exception as e:
            log.warning("РЎРѓР В±Р С•Р в„– Р С—РЎР‚Р С‘ Р Р†РЎвЂ№Р В·Р С•Р Р†Р Вµ Silero TTS: %s", e)
            return None

class XttsEngine(TTSEngine):
    """РРЅС‚РµРіСЂР°С†РёСЏ СЃ Р»РѕРєР°Р»СЊРЅС‹Рј XTTS v2 (С‡РµСЂРµР· xtts-api-server)."""

    def __init__(
        self,
        api_base: str = "http://localhost:8020",
        voice: str = "default.wav",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.voice = voice
        self.timeout = timeout
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return bool(self.api_base)

    async def synthesize(self, text: str, voice_name: str | None = None) -> tuple[bytes, str, float] | None:
        clean = clean_narration_text(text)
        if not clean:
            return None

        resolved_voice = voice_name or self.voice
        url = f"{self.api_base}/tts_to_audio/"
        
        payload = {
            "text": clean,
            "speaker_wav": resolved_voice,
            "language": "ru"
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                res = await client.post(url, json=payload)
                if res.status_code != 200:
                    log.warning("XTTS РѕС€РёР±РєР° %s: %s", res.status_code, res.text[:500])
                    return None
                
                audio_bytes = res.content
                duration = wav_duration(audio_bytes)
                return audio_bytes, "audio/wav", duration
        except Exception as e:
            log.warning("СЃР±РѕР№ РїСЂРё РІС‹Р·РѕРІРµ XTTS: %s", e)
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
            "silero": SileroTTS(api_base=settings.silero_api_base, voice=settings.silero_voice),
            "xtts": XttsEngine(api_base=settings.xtts_api_base, voice=settings.xtts_voice),
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
        if provider and provider != "gemini":
            voice_name = None
        return await engine.voice_for_narration(media_dir, campaign_id, narration_text, voice_name)

