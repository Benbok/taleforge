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
