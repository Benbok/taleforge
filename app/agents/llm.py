"""Обращение к моделям через LiteLLM (ТЗ, раздел 3): один интерфейс к Claude, Gemini и локальным моделям.

Ключи провайдеров — только в переменных окружения сервера (ANTHROPIC_API_KEY, GEMINI_API_KEY,
LM_STUDIO_API_BASE для локальной модели в LM Studio).
В тестах вместо LiteLLM подставляется ``ScriptedLLM`` с заранее заданными ответами.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.config import settings

log = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLMQuotaError(LLMError):
    """Provider quota failures have a safe player-facing reason and retry policy."""

    def __init__(self, *, budget_exhausted: bool = False):
        self.budget_exhausted = budget_exhausted
        super().__init__("исчерпан бюджет модели" if budget_exhausted else "исчерпана квота запросов модели")


def quota_error(message: str) -> LLMQuotaError | None:
    message = message.casefold()
    budget = any(
        text in message
        for text in (
            "monthly spending cap",
            "spending limit",
            "billing hard limit",
            "insufficient_quota",
        )
    )
    if budget or "resource_exhausted" in message or ("429" in message and "quota" in message):
        return LLMQuotaError(budget_exhausted=budget)
    return None


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
    reasoning_tokens: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    finish_reason: str | None = None
    blocked: bool = False
    blocked_metadata: dict[str, Any] = field(default_factory=dict)
    tokens_cached: int | None = None
    cost_known: bool = False


def reply_audit_error(reply: LLMReply, *, require_text: bool = False, reason: str | None = None) -> str | None:
    """Record invalid output and termination metadata without copying provider text."""
    if reason is None:
        if require_text and not reply.text.strip():
            reason = "empty_response"
        elif reply.blocked:
            reason = "blocked_response"
        elif reply.finish_reason and reply.finish_reason not in {"stop", "tool_calls", "function_call"}:
            reason = "incomplete_response"
    if reason is None:
        return None
    return json.dumps(
        {
            "reason": reason,
            "finish_reason": reply.finish_reason,
            "blocked": reply.blocked,
            "blocked_metadata": reply.blocked_metadata,
        },
        ensure_ascii=False,
    )


def reasoning_of(usage: Any) -> int:
    """Токены рассуждений из usage LiteLLM; у провайдеров без них — 0. Обычно уже входят в completion_tokens."""
    details = _usage_field(usage, "completion_tokens_details")
    return int(_usage_field(details, "reasoning_tokens") or 0)


def _usage_field(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def cached_tokens_of(usage: Any) -> int | None:
    """Provider prompt total already includes cached reads; absent metadata stays unknown."""
    details = _usage_field(usage, "prompt_tokens_details")
    value = _usage_field(details, "cached_tokens")
    if value is None:
        value = _usage_field(usage, "cache_read_input_tokens")
    return int(value) if value is not None else None


def _response_cost(litellm: Any, response: Any) -> tuple[float, bool]:
    if response is None:
        return 0.0, False
    try:
        value = litellm.completion_cost(completion_response=response)
        return (float(value), True) if value is not None else (0.0, False)
    except Exception:  # noqa: BLE001 — unknown tariffs are not evidence of a free call
        return 0.0, False


def _termination_metadata(response: Any, choice: Any, message: Any) -> dict[str, Any]:
    """Keep provider block reasons, while excluding refusal text and hidden parameters."""
    finish_reason = getattr(choice, "finish_reason", None)
    blocked = finish_reason in {"content_filter", "safety", "blocked", "refusal"}
    metadata: dict[str, Any] = {}
    for obj in (response, choice, message):
        if obj is None:
            continue
        fields = getattr(obj, "provider_specific_fields", None) or {}
        feedback = (
            fields.get("prompt_feedback") or fields.get("promptFeedback") or getattr(obj, "prompt_feedback", None)
        )
        if feedback:
            if hasattr(feedback, "model_dump"):
                feedback = feedback.model_dump(exclude_none=True)
            if isinstance(feedback, dict):
                block_reason = feedback.get("block_reason") or feedback.get("blockReason")
                if block_reason and block_reason != "BLOCK_REASON_UNSPECIFIED":
                    metadata["block_reason"] = str(block_reason)[:128]
                    blocked = True
        if getattr(obj, "refusal", None) or fields.get("refusal"):
            metadata["refusal"] = True
            blocked = True
        filters = getattr(obj, "content_filter_results", None) or fields.get("content_filter_results")
        if isinstance(filters, dict):
            filtered = [k for k, v in filters.items() if isinstance(v, dict) and v.get("filtered")]
            if filtered:
                metadata["filtered_categories"] = filtered
                blocked = True
    return {"finish_reason": finish_reason, "blocked": blocked, "blocked_metadata": metadata}


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


TRANSIENT_STATUS = frozenset({500, 502, 503, 504})  # перегрузка/сбой у провайдера: повтор обычно проходит
RETRY_DELAYS = (1.0, 3.0)  # секунд до второй и третьей попытки; дольше игроки ждать не должны


def _transient(e: Exception) -> bool:
    return getattr(e, "status_code", None) in TRANSIENT_STATUS


async def _with_retry(call):
    """Короткий повтор временных ошибок провайдера (503 «high demand»): один такой сбой не роняет весь ход.
    Квоты, лимит расходов и ошибки запроса не повторяются — их разбирает вызывающий код."""
    import asyncio

    for delay in (*RETRY_DELAYS, None):
        try:
            return await call()
        except Exception as e:  # noqa: BLE001
            if delay is None or not _transient(e):
                raise
            log.warning("временная ошибка провайдера (%s), повтор через %s с", getattr(e, "status_code", "?"), delay)
            await asyncio.sleep(delay)


class LiteLLMClient:
    def __init__(self):
        # Shared by narration, parsing and background authors using this client.
        self._quota_blocks: dict[str, tuple[float | None, LLMQuotaError]] = {}

    def check_quota(self, model: str) -> None:
        provider = model.split("/", 1)[0]
        block = self._quota_blocks.get(provider)
        if block is not None:
            retry_at, error = block
            if retry_at is None or time.monotonic() < retry_at:
                raise error
            del self._quota_blocks[provider]

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
        self.check_quota(model)
        import litellm

        msgs = messages
        # Gemini rejects explicit caches below a model-specific token minimum.
        # A character count cannot establish that minimum; leave caching to the
        # provider instead of making short parser requests fail with HTTP 400.
        if model.startswith("anthropic/"):
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
            # Адаптер LiteLLM переводит required в Gemini ANY; auto разрешил бы ответ без инструмента.
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
            resp = await _with_retry(lambda: litellm.acompletion(**kwargs))
        except Exception as e:  # noqa: BLE001 — любая ошибка провайдера останавливает ход, а не сервер
            quota = quota_error(str(e))
            if quota is not None:
                retry_at = None if quota.budget_exhausted else time.monotonic() + 60
                self._quota_blocks[model.split("/", 1)[0]] = (retry_at, quota)
                raise quota from e
            raise LLMError(f"{type(e).__name__}: {e}") from e
        latency = int((time.monotonic() - started) * 1000)

        if stream_callback:
            return await _collect_stream(litellm, resp, model, msgs, stream_callback, started)

        choices = getattr(resp, "choices", None)
        choice = choices[0] if choices else None
        msg = choice.message if choice else None
        calls = [
            ToolCall(tc.id, tc.function.name, _parse_args(tc.function.arguments), tc.function.arguments or "")
            for tc in (getattr(msg, "tool_calls", None) or [])
        ]
        cost, cost_known = _response_cost(litellm, resp)
        usage = getattr(resp, "usage", None)
        history = msg.model_dump(exclude_none=True) if hasattr(msg, "model_dump") else dict(msg) if msg else {}
        history["role"] = "assistant"
        return LLMReply(
            text=getattr(msg, "content", None) or "",
            tool_calls=calls,
            message=history,
            model=getattr(resp, "model", model) or model,
            tokens_in=int(getattr(usage, "prompt_tokens", 0) or 0),
            tokens_out=int(getattr(usage, "completion_tokens", 0) or 0),
            reasoning_tokens=reasoning_of(usage),
            tokens_cached=cached_tokens_of(usage),
            cost_known=cost_known,
            cost=cost,
            latency_ms=latency,
            **_termination_metadata(resp, choice, msg),
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
    cost, cost_known = _response_cost(litellm, full)
    # stream_chunk_builder reconstructs the assistant message, including tool calls.
    # Previously streaming silently discarded them, so game actions could be lost.
    choices = getattr(full, "choices", None)
    choice = choices[0] if choices else None
    msg = choice.message if choice else None
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
    termination = _termination_metadata(full, choice, msg)
    # Some builders omit the final reason or provider feedback from the rebuilt reply.
    for chunk in raw:
        chunk_choices = getattr(chunk, "choices", None)
        chunk_choice = chunk_choices[0] if chunk_choices else None
        info = _termination_metadata(chunk, chunk_choice, getattr(chunk_choice, "delta", None))
        if info["finish_reason"]:
            termination["finish_reason"] = info["finish_reason"]
        termination["blocked"] |= info["blocked"]
        termination["blocked_metadata"].update(info["blocked_metadata"])
    return LLMReply(
        text=text,
        tool_calls=calls,
        message=history,
        model=getattr(full, "model", None) or model,
        tokens_in=int(getattr(usage, "prompt_tokens", 0) or 0),
        tokens_out=int(getattr(usage, "completion_tokens", 0) or 0),
        reasoning_tokens=reasoning_of(usage),
        tokens_cached=cached_tokens_of(usage),
        cost_known=cost_known,
        cost=cost,
        latency_ms=latency,
        **termination,
    )


Script = Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], LLMReply | dict]


class ScriptedLLM:
    """Модель для тестов: отдаёт ответы по очереди. Ответ — LLMReply, словарь {text, tool_calls: [(name, args)]}
    или функция от (messages, tools). Все запросы сохраняются в ``requests``; запросы фонового режиссёра —
    в ``director_requests`` (ответ — элемент с пометкой director и arguments, иначе «без изменений»)."""

    def __init__(self, replies: list[Any]):
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.parser_requests: list[dict[str, Any]] = []
        self.voice_requests: list[dict[str, Any]] = []
        self.intro_requests: list[dict[str, Any]] = []
        self.director_requests: list[dict[str, Any]] = []
        self.greeting_requests: list[dict[str, Any]] = []

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
        if _is_greeting(messages):
            # приветствие мастера перед первой сессией: как вступление, сценарный ответ с пометкой greeting
            self.greeting_requests.append(req)
            scripted = next((r for r in self.replies if isinstance(r, dict) and r.get("greeting")), None)
            if scripted is None:
                return LLMReply(text="Добро пожаловать за стол, друзья!", model=model, tokens_in=10, tokens_out=5)
            self.replies.remove(scripted)
            return LLMReply(text=scripted.get("text", ""), model=model, tokens_in=10, tokens_out=5)
        if _is_director(tools):
            # фоновый режиссёр идёт параллельно ходам: сценарный ответ с пометкой director, иначе «без изменений»
            self.director_requests.append(req)
            scripted = next((r for r in self.replies if isinstance(r, dict) and r.get("director")), None)
            if scripted is not None:
                self.replies.remove(scripted)
            args = (scripted or {}).get("arguments") or {"summary": "no_change", "operations": []}
            call = ToolCall(f"call_d{len(self.director_requests)}", "propose_adaptation", args, json.dumps(args))
            return LLMReply(text="", tool_calls=[call], model=model, tokens_in=10, tokens_out=5)
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


def _is_greeting(messages: list[dict[str, Any]]) -> bool:
    return any(isinstance(m.get("content"), str) and "Поприветствуй игроков" in m["content"] for m in messages)


def _is_director(tools) -> bool:
    return any(((t or {}).get("function") or {}).get("name") == "propose_adaptation" for t in tools or [])


def _is_campaign_intro(messages: list[dict[str, Any]]) -> bool:
    return any(isinstance(m.get("content"), str) and "вступление ко всей кампании" in m["content"] for m in messages)
