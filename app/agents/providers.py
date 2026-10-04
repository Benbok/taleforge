"""Провайдеры моделей для админки: задан ли ключ, какие модели видит LM Studio, отвечает ли модель.

Ключи читаются из окружения сервера и наружу не отдаются: интерфейс узнаёт только, задан ли ключ.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import Any

from app.agents.llm import LLM, LLMError, model_for
from app.config import settings

LM_STUDIO_DEFAULT_BASE = "http://localhost:1234/v1"
PROVIDER_INFO = {
    "claude": {"title": "Claude (Anthropic)", "key_env": ("ANTHROPIC_API_KEY",)},
    "gemini": {"title": "Gemini (Google)", "key_env": ("GEMINI_API_KEY", "GOOGLE_API_KEY")},
    "local": {"title": "Локальная модель (LM Studio)", "key_env": ()},
}
CHECK_PROMPT = "Проверка связи. Ответь одним словом: «готов»."
CHECK_TIMEOUT_SEC = 60.0


ERROR_HINTS = {
    "AuthenticationError": "провайдер отклонил ключ: проверьте ключ в окружении сервера",
    "PermissionDeniedError": "у ключа нет доступа к этой модели",
    "NotFoundError": "провайдер не знает такую модель: проверьте имя",
    "BadRequestError": "провайдер отклонил запрос: проверьте имя модели",
    "RateLimitError": "превышен лимит запросов или закончились средства на счёте",
    "APIConnectionError": "нет связи с сервером модели: он запущен и адрес верный?",
    "Timeout": "сервер модели не ответил вовремя",
    "ServiceUnavailableError": "сервер модели временно недоступен",
    "InternalServerError": "ошибка на стороне провайдера",
}


def explain(error: str) -> str:
    """Понятная причина сбоя плюс исходный текст ошибки провайдера для диагностики."""
    kind = error.split(":", 1)[0].strip()
    hint = ERROR_HINTS.get(kind)
    return f"{hint} ({error[:300]})" if hint else error[:500]


def local_api_base(api_base: str | None = None) -> str:
    from app.config import _env

    return (api_base or _env("LM_STUDIO_API_BASE") or LM_STUDIO_DEFAULT_BASE).rstrip("/")


def provider_status() -> list[dict[str, Any]]:
    out = []
    active = settings.llm_provider
    for pid, info in PROVIDER_INFO.items():
        keys = info["key_env"]

        main_model = None
        technical_model = None
        if pid == "claude":
            main_model = settings.claude_main_model
            technical_model = settings.claude_technical_model
        elif pid == "gemini":
            main_model = settings.gemini_main_model
            technical_model = settings.gemini_technical_model
        elif pid == "local":
            main_model = settings.local_main_model
            technical_model = settings.local_technical_model

        out.append(
            {
                "id": pid,
                "title": info["title"],
                "key_env": keys[0] if keys else None,
                "key_set": any(os.environ.get(k) for k in keys) if keys else None,
                "main_model": main_model,
                "technical_model": technical_model,
                "api_base": local_api_base() if pid == "local" else None,
                "is_active": pid == active,
            }
        )
    return out


async def list_local_models(api_base: str | None = None) -> list[str]:
    """Модели, загруженные в LM Studio (OpenAI-совместимый ``GET /models``)."""
    import httpx

    base = local_api_base(api_base)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base}/models")
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise LLMError(f"LM Studio по адресу {base} не отвечает: {type(e).__name__}") from e
    return sorted(str(m.get("id")) for m in data.get("data", []) if isinstance(m, dict) and m.get("id"))


async def check_model(
    llm: LLM, provider: str, model: str | None, api_base: str | None = None, timeout: float = CHECK_TIMEOUT_SEC
) -> dict[str, Any]:
    """Короткий запрос к модели. Результат пишется в профиль модели и показывается админу."""
    at = datetime.now(UTC).isoformat()
    try:
        name = model_for(provider, model)
    except LLMError as e:
        return {"ok": False, "at": at, "error": str(e)}
    info = PROVIDER_INFO.get(provider)
    if info and info["key_env"] and not any(os.environ.get(k) for k in info["key_env"]):
        return {"ok": False, "at": at, "model": name, "error": f"на сервере не задан ключ {info['key_env'][0]}"}
    base = local_api_base(api_base) if provider == "local" else None
    try:
        reply = await asyncio.wait_for(
            llm.complete([{"role": "user", "content": CHECK_PROMPT}], model=name, max_tokens=32, api_base=base),
            timeout,
        )
    except TimeoutError:
        return {"ok": False, "at": at, "model": name, "error": f"модель не ответила за {int(timeout)} с"}
    except LLMError as e:
        return {"ok": False, "at": at, "model": name, "error": explain(str(e))}
    return {
        "ok": True,
        "at": at,
        "model": reply.model or name,
        "reply": (reply.text or "").strip()[:200],
        "latency_ms": reply.latency_ms,
        "cost": reply.cost,
    }
