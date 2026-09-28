"""Обращение к моделям через LiteLLM (ТЗ, раздел 3): один интерфейс к Claude, Gemini и локальным моделям.

Ключи провайдеров — только в переменных окружения сервера (ANTHROPIC_API_KEY, GEMINI_API_KEY,
LM_STUDIO_API_BASE для локальной модели в LM Studio).
В тестах вместо LiteLLM подставляется ``ScriptedLLM`` с заранее заданными ответами.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# Модель по умолчанию для мастера: сильная, с хорошим творческим письмом (раздел 3, «Абстракция провайдеров»).
DEFAULT_MODELS = {"claude": "anthropic/claude-opus-5"}
# Парсер намерений — дешёвая быстрая модель (раздел 6). У остальных провайдеров парсер работает на модели мастера.
PARSER_MODELS = {"claude": "anthropic/claude-haiku-4-5"}
# local — модель, запущенная в LM Studio (OpenAI-совместимый сервер)
PROVIDER_PREFIX = {"claude": "anthropic/", "gemini": "gemini/", "local": "lm_studio/"}


class LLMError(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


@dataclass
class LLMReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    message: dict[str, Any] = field(default_factory=dict)  # ответ ассистента для истории (с блоками рассуждений)
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    latency_ms: int = 0


class LLM(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        api_base: str | None = None,
    ) -> LLMReply: ...


def model_for(provider: str, model: str | None) -> str:
    """Имя модели для LiteLLM. Пустая модель у Claude — модель мастера по умолчанию; у других провайдеров
    модель нужно указать при создании кампании."""
    if model:
        prefix = PROVIDER_PREFIX.get(provider, "")
        if prefix and not model.startswith(prefix):
            return prefix + model
        return model
    if provider in DEFAULT_MODELS:
        return DEFAULT_MODELS[provider]
    raise LLMError(f"для провайдера {provider} укажите модель в настройках мастера кампании")


def parser_model_for(provider: str, model: str | None) -> str:
    return PARSER_MODELS.get(provider) or model_for(provider, model)


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {"__invalid_json__": str(raw)[:500]}
    return v if isinstance(v, dict) else {"__invalid_json__": str(raw)[:500]}


class LiteLLMClient:
    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        api_base: str | None = None,
    ) -> LLMReply:
        import litellm

        kwargs: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if api_base:
            kwargs["api_base"] = api_base
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        # У новых моделей Claude параметры сэмплирования убраны: температура уходит только другим провайдерам
        if temperature is not None and not model.startswith("anthropic/"):
            kwargs["temperature"] = temperature
        started = time.monotonic()
        try:
            resp = await litellm.acompletion(**kwargs)
        except Exception as e:  # noqa: BLE001 — любая ошибка провайдера останавливает ход, а не сервер
            raise LLMError(f"{type(e).__name__}: {e}") from e
        latency = int((time.monotonic() - started) * 1000)
        choice = resp.choices[0]
        msg = choice.message
        calls = [
            ToolCall(tc.id, tc.function.name, _parse_args(tc.function.arguments), tc.function.arguments or "")
            for tc in (msg.tool_calls or [])
        ]
        try:
            cost = float(litellm.completion_cost(completion_response=resp) or 0.0)
        except Exception:  # noqa: BLE001 — у локальных моделей цены нет
            cost = 0.0
        usage = getattr(resp, "usage", None)
        history = msg.model_dump(exclude_none=True) if hasattr(msg, "model_dump") else dict(msg)
        history["role"] = "assistant"
        return LLMReply(
            text=msg.content or "",
            tool_calls=calls,
            message=history,
            model=getattr(resp, "model", model) or model,
            tokens_in=int(getattr(usage, "prompt_tokens", 0) or 0),
            tokens_out=int(getattr(usage, "completion_tokens", 0) or 0),
            cost=cost,
            latency_ms=latency,
        )


Script = Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], LLMReply | dict]


class ScriptedLLM:
    """Модель для тестов: отдаёт ответы по очереди. Ответ — LLMReply, словарь {text, tool_calls: [(name, args)]}
    или функция от (messages, tools). Все запросы сохраняются в ``requests``."""

    def __init__(self, replies: list[Any]):
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.parser_requests: list[dict[str, Any]] = []

    async def complete(
        self, messages, *, model, tools=None, max_tokens=4096, temperature=None, api_base=None
    ) -> LLMReply:
        req = {"messages": [dict(m) for m in messages], "tools": tools, "model": model, "api_base": api_base}
        auto = _auto_tool(tools)
        if auto and not self._next_is(auto):
            # Парсер намерений и сводки в тестах, где их ответ не задан: действие без разбора, пустая сводка.
            # Такие запросы идут в parser_requests, чтобы не сдвигать нумерацию запросов мастера.
            self.parser_requests.append(req)
            args = AUTO_REPLIES[auto]
            call = ToolCall(f"call_p{len(self.parser_requests)}", auto, args, json.dumps(args))
            return LLMReply(text="", tool_calls=[call], model=model, tokens_in=10, tokens_out=5)
        self.requests.append(req)
        if not self.replies:
            raise LLMError("ScriptedLLM: ответы закончились")
        r = self.replies.pop(0)
        if callable(r):
            r = r(messages, tools)
        if isinstance(r, LLMReply):
            return r
        calls = [
            ToolCall(f"call_{len(self.requests)}_{i}", name, args, json.dumps(args))
            for i, (name, args) in enumerate(r.get("tool_calls") or [])
        ]
        message: dict[str, Any] = {"role": "assistant", "content": r.get("text", "")}
        if calls:
            message["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.raw_arguments}}
                for c in calls
            ]
        return LLMReply(
            text=r.get("text", ""), tool_calls=calls, message=message, model=model, tokens_in=10, tokens_out=5
        )

    def _next_is(self, tool: str) -> bool:
        r = self.replies[0] if self.replies else None
        return isinstance(r, dict) and any(name == tool for name, _ in r.get("tool_calls") or [])


AUTO_REPLIES = {
    "submit_intent": {"kind": "action", "actions": [{"verb": "custom"}], "confidence": 1.0},
    "submit_summary": {"events": ["(сводка тестовой модели)"], "recap": "Герои продолжают путь."},
}


def _auto_tool(tools) -> str | None:
    names = {t.get("function", {}).get("name") for t in tools or []}
    return next((n for n in AUTO_REPLIES if n in names), None)
