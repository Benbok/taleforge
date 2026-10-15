"""The default suite must never spend credentials inherited from local settings."""

import asyncio

import litellm
import pytest

from app.agents.llm import LiteLLMClient, LLMError


def test_provider_boundary_rejects_live_completion():
    with pytest.raises(AssertionError, match="Live LiteLLM requests are disabled"):
        asyncio.run(litellm.acompletion(model="gemini/offline-guard", messages=[]))


def test_real_client_cannot_escape_offline_guard():
    with pytest.raises(LLMError, match="Live LiteLLM requests are disabled"):
        asyncio.run(LiteLLMClient().complete([], model="gemini/offline-guard"))
