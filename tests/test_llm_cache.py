"""Provider caching must not break short intent-parser requests."""

import asyncio
from types import SimpleNamespace

import pytest

from app.agents.llm import LiteLLMClient, LLMError


@pytest.mark.parametrize("model", ["gemini/gemini-2.5-flash-lite", "gemini/gemini-2.5-flash"])
def test_short_gemini_prompt_works_without_explicit_cache(monkeypatch, model):
    import litellm

    async def provider(**kwargs):
        if any(isinstance(m["content"], list) for m in kwargs["messages"]):
            raise ValueError("Cached content is too small. total_token_count=1351, min_total_token_count=2048")
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="Речь", tool_calls=[], model_dump=lambda **_: {}))
            ],
            usage=SimpleNamespace(prompt_tokens=1351, completion_tokens=1),
            model=model,
        )

    monkeypatch.setattr(litellm, "acompletion", provider)
    reply = asyncio.run(
        LiteLLMClient().complete(
            [
                {"role": "system", "content": "Правила разбора намерений. " * 100},
                {"role": "user", "content": "А ты Эмрис, че тут делаешь?"},
            ],
            model=model,
        )
    )
    assert reply.text == "Речь"


def test_other_provider_errors_are_not_swallowed(monkeypatch):
    import litellm

    async def provider(**kwargs):
        raise ValueError("Invalid API key")

    monkeypatch.setattr(litellm, "acompletion", provider)
    with pytest.raises(LLMError, match="Invalid API key"):
        asyncio.run(
            LiteLLMClient().complete([{"role": "system", "content": "Правила"}], model="gemini/gemini-2.5-flash-lite")
        )
