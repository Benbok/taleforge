import asyncio
from types import SimpleNamespace

import pytest

from app.agents.llm import LiteLLMClient


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    "model,expected",
    [
        ("gemini/gemini-3.5-flash-lite", None),
        ("gemini/gemini-3-flash-preview", None),
        ("vertex_ai/gemini-3.1-pro-preview", None),
        ("gemini/gemini-4-flash", None),
        ("gemini/gemini-2.5-flash-lite", 0.2),
        ("vertex_ai/gemini-2.5-pro", 0.2),
        ("anthropic/claude-sonnet-4-6", None),
        ("lm_studio/local-model", 0.2),
        ("openai/gemini-3-local", 0.2),
    ],
)
def test_sampling_parameters_follow_provider_capabilities(monkeypatch, model, expected, streaming):
    import litellm

    captured = {}

    async def empty_stream():
        if False:
            yield

    async def complete(**kwargs):
        captured.update(kwargs)
        if streaming:
            return empty_stream()
        return SimpleNamespace(choices=[], usage=None, model=model)

    monkeypatch.setattr(litellm, "acompletion", complete)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0)
    messages = [{"role": "system", "content": "Return concise factual answers."}]
    asyncio.run(
        LiteLLMClient().complete(
            messages,
            model=model,
            temperature=0.2,
            stream_callback=(lambda _: None) if streaming else None,
        )
    )
    assert captured.get("temperature") == expected
    if expected is None:
        assert "temperature" not in captured
    assert "top_p" not in captured and "top_k" not in captured
    assert captured["messages"] == messages
