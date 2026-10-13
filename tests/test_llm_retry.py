"""Временная перегрузка провайдера не роняет ход: короткий повтор (плейтест вдвоём, 503 Gemini)."""

import asyncio
from types import SimpleNamespace

import pytest

import app.agents.llm as llm_mod
from app.agents.llm import LiteLLMClient, LLMError


class Unavailable(Exception):
    status_code = 503


class BadRequest(Exception):
    status_code = 400


def _reply():
    msg = SimpleNamespace(content="ок", tool_calls=[], model_dump=lambda **_: {"content": "ок"})
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], model="m", usage=None)


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm_mod, "RETRY_DELAYS", (0, 0))


def test_transient_provider_error_is_retried(monkeypatch, no_sleep):
    import litellm

    calls = []

    async def complete(**_):
        calls.append(1)
        if len(calls) < 3:
            raise Unavailable("This model is currently experiencing high demand")
        return _reply()

    monkeypatch.setattr(litellm, "acompletion", complete)
    monkeypatch.setattr(litellm, "completion_cost", lambda **kw: 0)
    reply = asyncio.run(LiteLLMClient().complete([], model="gemini/x"))
    assert reply.text == "ок" and len(calls) == 3


def test_permanent_provider_error_is_not_retried(monkeypatch, no_sleep):
    import litellm

    calls = []

    async def complete(**_):
        calls.append(1)
        raise BadRequest("schema too complex")

    monkeypatch.setattr(litellm, "acompletion", complete)
    with pytest.raises(LLMError):
        asyncio.run(LiteLLMClient().complete([], model="gemini/x"))
    assert len(calls) == 1


def test_persistent_overload_gives_up_after_bounded_retries(monkeypatch, no_sleep):
    import litellm

    calls = []

    async def complete(**_):
        calls.append(1)
        raise Unavailable("overloaded")

    monkeypatch.setattr(litellm, "acompletion", complete)
    with pytest.raises(LLMError):
        asyncio.run(LiteLLMClient().complete([], model="gemini/x"))
    assert len(calls) == 3
