"""Обязательный вызов инструмента сохраняется на границе клиента и адаптера Gemini."""

import asyncio
from types import SimpleNamespace

import pytest

from app.agents.llm import LiteLLMClient


@pytest.mark.parametrize("model", ["gemini/test", "anthropic/test", "lm_studio/test"])
def test_required_tool_choice_is_not_downgraded(monkeypatch, model):
    import litellm
    from litellm.llms.vertex_ai.gemini.vertex_and_google_ai_studio_gemini import VertexGeminiConfig

    seen = {}

    async def complete(**kwargs):
        seen.update(kwargs)
        msg = SimpleNamespace(content="", tool_calls=[], model_dump=lambda **_: {"content": ""})
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], model=model, usage=None)

    monkeypatch.setattr(litellm, "acompletion", complete)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0)
    tools = [{"type": "function", "function": {"name": "submit_layout", "parameters": {"type": "object"}}}]
    asyncio.run(LiteLLMClient().complete([], model=model, tools=tools, tool_choice="required"))
    assert seen["tool_choice"] == "required"
    if model.startswith("gemini/"):
        config = VertexGeminiConfig().map_tool_choice_values(model, seen["tool_choice"])
        assert config["functionCallingConfig"]["mode"] == "ANY"


@pytest.mark.parametrize(
    "model,disabled",
    [
        ("gemini/gemini-2.5-flash", True),
        ("gemini/gemini-2.5-flash-lite", True),
        ("gemini/gemini-3.5-flash-lite", False),
        ("gemini/future-flash", False),
        ("gemini/gemini-2.5-pro", False),
    ],
)
def test_thinking_disable_uses_verified_exact_models(monkeypatch, model, disabled):
    import litellm

    captured = {}

    async def complete(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[], usage=None, model=model)

    monkeypatch.setattr(litellm, "acompletion", complete)
    asyncio.run(LiteLLMClient().complete([], model=model, thinking=False))
    assert (captured.get("reasoning_effort") == "disable") is disabled


def test_master_ask_forwards_explicit_call_options():
    from app.agents.llm import LLMReply
    from app.agents.master.turn import TurnMixin

    captured = {}

    class Client:
        async def complete(self, messages, **options):
            captured.update(options)
            return LLMReply(text="ok", model="m")

    master = TurnMixin()
    master.llm = Client()
    cfg = SimpleNamespace(settings={}, temperature=0.3)
    asyncio.run(
        master._ask([], cfg, "c", "s", None, "review", [], [], tool_choice="required", max_tokens=512, thinking=False)
    )
    assert captured["tool_choice"] == "required" and captured["max_tokens"] == 512
    assert captured["thinking"] is False
