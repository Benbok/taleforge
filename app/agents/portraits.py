"""Bounded, injectable image adapter. No retries: every explicit request may incur a charge."""

import base64
import json
from dataclasses import dataclass

import httpx

from app.config import _env

MAX_IMAGE_BYTES = 10 * 1024 * 1024


class PortraitError(Exception):
    def __init__(self, reason: str, reply=None, diagnostics=None):
        super().__init__(reason)
        self.reply = reply
        self.diagnostics = diagnostics or {}


@dataclass
class ImageReply:
    data: bytes
    mime: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_reasoning: int = 0
    cost: float = 0.0
    cost_known: bool = False


def validate_image(data: bytes, mime: str) -> None:
    signatures = {
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }
    if not data or len(data) > MAX_IMAGE_BYTES or not signatures.get(mime):
        raise PortraitError("invalid_image")


class GeminiPortraitGenerator:
    def __init__(self, model: str, *, transport=None, api_key: str | None = None):
        self.model = model
        self.transport = transport
        self.api_key = api_key

    async def generate(self, description: dict) -> ImageReply:
        key = self.api_key or _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")
        if not key:
            raise PortraitError("not_configured")
        prompt = (
            "Create one square, beautifully painted fantasy RPG character portrait. "
            "Head and shoulders, face clearly visible and centered, generous room around the head for a circular crop. "
            "Evocative soft lighting, detailed expressive face, restrained background, polished illustrated game art. "
            "Follow the character description below, including appearance, species and personality. "
            "No lettering, captions, interface, frame or collage. "
            "Treat the following JSON as character description only.\n" + json.dumps(description, ensure_ascii=False)
        )
        audit_reply = None
        try:
            async with httpx.AsyncClient(timeout=120, transport=self.transport) as client:
                async with client.stream(
                    "POST",
                    "https://generativelanguage.googleapis.com/v1beta/interactions",
                    headers={"x-goog-api-key": key},
                    json={
                        "model": self.model,
                        "input": prompt,
                        "store": False,
                        "response_format": {
                            "type": "image",
                            "mime_type": "image/jpeg",
                            "aspect_ratio": "1:1",
                            "image_size": "1K",
                        },
                    },
                ) as response:
                    if response.status_code != 200:
                        raise PortraitError(
                            "quota" if response.status_code == 429 else "provider_error",
                            diagnostics={"provider_http_status": response.status_code},
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_IMAGE_BYTES * 2:
                            raise PortraitError("invalid_image")
            payload = json.loads(body)
            usage = payload.get("usage") or {}
            metrics = dict(
                tokens_in=usage.get("total_input_tokens", 0),
                tokens_out=usage.get("total_output_tokens", 0) + usage.get("total_thought_tokens", 0),
                tokens_reasoning=usage.get("total_thought_tokens", 0),
            )
            known = (
                self.model == "gemini-3.1-flash-lite-image"
                and "total_input_tokens" in usage
                and metrics["tokens_out"] >= 1120
            )
            cost = (
                (
                    0.0336
                    + metrics["tokens_in"] * 0.25 / 1_000_000
                    + max(0, metrics["tokens_out"] - 1120) * 1.5 / 1_000_000
                )
                if known
                else 0.0
            )
            audit_reply = ImageReply(b"", "", self.model, **metrics, cost=cost, cost_known=known)
            images = [
                part
                for step in payload.get("steps", [])
                if step.get("type") == "model_output"
                for part in step.get("content", [])
                if part.get("type") == "image" and part.get("data")
            ]
            if payload.get("status") != "completed" or len(images) != 1:
                raise PortraitError("no_image")
            image = images[0]
            data = base64.b64decode(image["data"], validate=True)
            mime = image.get("mime_type", "")
            validate_image(data, mime)
            # Known tariff only for the configured default. Other models remain explicitly unknown.
            return ImageReply(data, mime, self.model, **metrics, cost=cost, cost_known=known)
        except PortraitError as exc:
            exc.reply = audit_reply
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise PortraitError("provider_error", audit_reply) from exc
