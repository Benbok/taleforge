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

from app.config import settings


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
        tool_choice: Any = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        api_base: str | None = None,
        stream_callback: Callable[[str], Any] | None = None,
        thinking: bool = True,
    ) -> LLMReply: ...


def _get_provider() -> str:
    return settings.llm_provider


def _ensure_prefix(p: str, m: str) -> str:
    prefixes = {"claude": "anthropic/", "gemini": "gemini/", "local": "lm_studio/"}
    prefix = prefixes.get(p, "")
    if prefix and not m.startswith(prefix):
        return prefix + m
    return m


def model_for(provider: str | None = None, model: str | None = None) -> str:
    """Gets the main model for a provider from settings."""
    p = provider or _get_provider()
    if model:
        return _ensure_prefix(p, model)

    if p == "gemini":
        return _ensure_prefix(p, settings.gemini_main_model)
    elif p == "claude":
        return _ensure_prefix(p, settings.claude_main_model)
    elif p == "local":
        return _ensure_prefix(p, settings.local_main_model)
    raise LLMError(f"Unknown provider '{p}'")


def parser_model_for(provider: str | None = None, model: str | None = None) -> str:
    """Gets the technical/parser model for a provider from settings."""
    p = provider or _get_provider()
    if model:
        return _ensure_prefix(p, model)

    if p == "gemini":
        return _ensure_prefix(p, settings.gemini_technical_model)
    elif p == "claude":
        return _ensure_prefix(p, settings.claude_technical_model)
    elif p == "local":
        return _ensure_prefix(p, settings.local_technical_model)
    raise LLMError(f"Unknown provider '{p}'")


def decide_model_for() -> str:
    """Модель фазы решения хода (выбор инструментов и бросков): техническая, DECIDE_MODEL=main вернёт основную."""
    return model_for() if settings.decide_model == "main" else parser_model_for()


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
        tool_choice: Any = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        api_base: str | None = None,
        stream_callback: Callable[[str], Any] | None = None,
        thinking: bool = True,
    ) -> LLMReply:
        """``tool_choice="required"`` — модель обязана ответить вызовом инструмента, а не текстом.
        ``thinking=False`` — художественный текст без скрытых рассуждений: у Gemini 2.5 они входят в max_tokens
        и обрезают ответ на полуслове, да и ждать их дольше."""
        import litellm

        msgs = messages
        if model.startswith("gemini/") or model.startswith("anthropic/"):
            cached_messages = []
            for m in messages:
                if m.get("role") == "system" and isinstance(m.get("content"), str) and len(m["content"]) > 1000:
                    cached_messages.append(
                        {
                            **m,
                            "content": [{"type": "text", "text": m["content"], "cache_control": {"type": "ephemeral"}}],
                        }
                    )
                else:
                    cached_messages.append(m)
            msgs = cached_messages

        kwargs: dict[str, Any] = {"model": model, "messages": msgs, "max_tokens": max_tokens}
        if api_base:
            kwargs["api_base"] = api_base
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice if tool_choice is not None else "auto"
        # У новых моделей Claude параметры сэмплирования убраны: температура уходит только другим провайдерам
        if temperature is not None and not model.startswith("anthropic/"):
            kwargs["temperature"] = temperature
        if not thinking and model.startswith("gemini/") and "flash" in model:
            kwargs["reasoning_effort"] = "disable"  # у Pro рассуждения не отключаются
        if stream_callback:
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}  # без этого поток не несёт токены и цену
        started = time.monotonic()
        try:
            resp = await litellm.acompletion(**kwargs)
        except Exception as e:  # noqa: BLE001 — любая ошибка провайдера останавливает ход, а не сервер
            raise LLMError(f"{type(e).__name__}: {e}") from e
        latency = int((time.monotonic() - started) * 1000)

        if stream_callback:
            return await _collect_stream(litellm, resp, model, msgs, stream_callback, started)

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


async def _collect_stream(litellm, resp, model: str, messages, stream_callback, started: float) -> LLMReply:
    """Отдаёт куски текста по мере прихода и собирает полный ответ с токенами и ценой для «Расходов»."""
    raw, parts = [], []
    try:
        async for chunk in resp:
            raw.append(chunk)
            delta = getattr(chunk.choices[0].delta, "content", None) if chunk.choices else None
            if delta:
                parts.append(delta)
                await stream_callback(delta)
    except Exception as e:  # noqa: BLE001 — обрыв потока останавливает ход так же, как ошибка провайдера
        raise LLMError(f"{type(e).__name__}: {e}") from e
    latency = int((time.monotonic() - started) * 1000)
    text = "".join(parts)
    full = litellm.stream_chunk_builder(raw, messages=messages) if raw else None
    usage = getattr(full, "usage", None)
    try:
        cost = float(litellm.completion_cost(completion_response=full) or 0.0) if full is not None else 0.0
    except Exception:  # noqa: BLE001 — у локальных моделей цены нет
        cost = 0.0
    # stream_chunk_builder reconstructs the assistant message, including tool calls.
    # Previously streaming silently discarded them, so game actions could be lost.
    choices = getattr(full, "choices", None)
    msg = choices[0].message if choices else None
    calls = [
        ToolCall(tc.id, tc.function.name, _parse_args(tc.function.arguments), tc.function.arguments or "")
        for tc in (getattr(msg, "tool_calls", None) or [])
    ]
    history = (
        msg.model_dump(exclude_none=True)
        if msg is not None and hasattr(msg, "model_dump")
        else dict(msg)
        if msg is not None
        else {"role": "assistant", "content": text}
    )
    history["role"] = "assistant"
    return LLMReply(
        text=text,
        tool_calls=calls,
        message=history,
        model=getattr(full, "model", None) or model,
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
        self.voice_requests: list[dict[str, Any]] = []
        self.intro_requests: list[dict[str, Any]] = []

    async def complete(
        self,
        messages,
        *,
        model,
        tools=None,
        tool_choice=None,
        max_tokens=4096,
        temperature=None,
        api_base=None,
        stream_callback=None,
        thinking=True,
    ) -> LLMReply:
        req = {"messages": [dict(m) for m in messages], "tools": tools, "model": model, "api_base": api_base}
        if tool_choice not in (None, "auto"):
            req["tool_choice"] = tool_choice
        if not thinking:
            req["thinking"] = False
        auto = _auto_tool(tools)
        if auto and not self._next_is(auto):
            # Парсер намерений и сводки в тестах, где их ответ не задан: действие без разбора, пустая сводка.
            # Такие запросы идут в parser_requests, чтобы не сдвигать нумерацию запросов мастера.
            self.parser_requests.append(req)
            args = AUTO_REPLIES[auto]
            call = ToolCall(f"call_p{len(self.parser_requests)}", auto, args, json.dumps(args))
            return LLMReply(text="", tool_calls=[call], model=model, tokens_in=10, tokens_out=5)
        if _is_voice_line(messages):
            # реплика озвучки идёт параллельно с повествованием: берём сценарный ответ с пометкой, где бы он ни стоял
            self.voice_requests.append(req)
            scripted = next((r for r in self.replies if isinstance(r, dict) and r.get("voice_line")), None)
            if scripted is None:
                return LLMReply(text="Осторожнее на выступе!", model=model, tokens_in=10, tokens_out=5)
            self.replies.remove(scripted)
            return LLMReply(text=scripted.get("text", ""), model=model, tokens_in=10, tokens_out=5)
        if _is_campaign_intro(messages):
            # вступление ко всей кампании готовится само после каркаса: тесты не обязаны его сценарировать,
            # а сценарный ответ с пометкой campaign_intro берётся, где бы он ни стоял в очереди
            self.intro_requests.append(req)
            scripted = next((r for r in self.replies if isinstance(r, dict) and r.get("campaign_intro")), None)
            if scripted is None:
                return LLMReply(text="Туман стелется над причалами.", model=model, tokens_in=10, tokens_out=5)
            self.replies.remove(scripted)
            return LLMReply(text=scripted.get("text", ""), model=model, tokens_in=10, tokens_out=5)
        if _is_emotion(messages):
            return LLMReply(
                text='{"anger": 0.0, "joy": 0.0, "suspicion": 0.0, "boredom": 0.0}',
                model=model,
                tokens_in=10,
                tokens_out=5,
            )
        self.requests.append(req)
        if not self.replies:
            raise LLMError("ScriptedLLM: ответы закончились")
        r = self.replies.pop(0)
        if callable(r):
            r = r(messages, tools)
        text_val = r.text if isinstance(r, LLMReply) else r.get("text", "")
        if stream_callback and text_val:
            import inspect

            if inspect.iscoroutinefunction(stream_callback):
                await stream_callback(text_val)
            else:
                res = stream_callback(text_val)
                if inspect.isawaitable(res):
                    await res
        if isinstance(r, LLMReply):
            return r
        calls = [
            ToolCall(f"call_{len(self.requests)}_{i}", name, args, json.dumps(args))
            for i, (name, args) in enumerate(r.get("tool_calls") or [])
        ]
        message: dict[str, Any] = {"role": "assistant", "content": text_val}
        if calls:
            message["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.raw_arguments}}
                for c in calls
            ]
        return LLMReply(text=text_val, tool_calls=calls, message=message, model=model, tokens_in=10, tokens_out=5)

    def _next_is(self, tool: str) -> bool:
        r = self.replies[0] if self.replies else None
        return isinstance(r, dict) and any(name == tool for name, _ in r.get("tool_calls") or [])


AUTO_REPLIES = {
    "submit_intent": {"kind": "action", "actions": [{"verb": "custom"}], "confidence": 1.0},
    "submit_summary": {"events": ["(сводка тестовой модели)"], "recap": "Герои продолжают путь."},
    "write_chronicle": {"notes": []},
    "submit_sketch": {"shape": "room", "cols": 4, "rows": 4, "party": [1, 1]},
}


def _auto_tool(tools) -> str | None:
    names = {t.get("function", {}).get("name") for t in tools or []}
    return next((n for n in AUTO_REPLIES if n in names), None)


def _is_voice_line(messages: list[dict[str, Any]]) -> bool:
    # по заголовку промпта voice_line.j2: широкие слова («реплики», «мастера») ловили и парсер, и повествование
    return any(
        isinstance(m.get("content"), str) and "Фаза эмоциональной реакции мастера" in m["content"] for m in messages
    )


def _is_emotion(messages: list[dict[str, Any]]) -> bool:
    for m in messages:
        c = m.get("content")
        if isinstance(c, str) and "анализатор эмоций" in c:
            return True
    return False


def _is_campaign_intro(messages: list[dict[str, Any]]) -> bool:
    return any(isinstance(m.get("content"), str) and "вступление ко всей кампании" in m["content"] for m in messages)
