"""Small checks for findings added after the first playtest fixes."""

import asyncio
import sys
from types import SimpleNamespace

import pytest

from app.agents.llm import LiteLLMClient, LLMQuotaError, quota_error
from tests.test_tools import call, game, play  # noqa: F401


def test_provider_budget_blocks_followup_network_calls(monkeypatch):
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("429 RESOURCE_EXHAUSTED: exceeded its monthly spending cap")

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=completion))
    client = LiteLLMClient()

    async def scenario():
        for model in ("gemini/main", "gemini/technical"):
            with pytest.raises(LLMQuotaError) as caught:
                await client.complete([], model=model)
            assert caught.value.budget_exhausted

    asyncio.run(scenario())
    assert len(calls) == 1
    assert quota_error("429 temporary quota exceeded").budget_exhausted is False
    assert quota_error("ordinary timeout") is None
