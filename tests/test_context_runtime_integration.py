"""Runtime assertions for context metadata attached to real LLM calls."""

from __future__ import annotations

import asyncio

import pytest

from app.agents.llm import ScriptedLLM
from app.agents.master.prompt_context import PromptBundle
from app.agents.master.service import MasterService
from app.core.llm_diagnostics import message_sizes
from app.db.models import AgentConfig


def _service(llm: ScriptedLLM) -> MasterService:
    service = object.__new__(MasterService)
    service.llm = llm
    return service


async def _ask_legacy(
    *,
    prompt_version: str,
    messages: list[dict],
    tools: list[dict] | None = None,
):
    llm = ScriptedLLM([{"text": "ok"}])
    captured: list[dict] = []
    complete = llm.complete

    async def intercepted(messages, **kwargs):
        captured.append({"messages": messages, **kwargs})
        return await complete(messages, **kwargs)

    llm.complete = intercepted
    bundle = PromptBundle(
        messages,
        {},
        version=prompt_version,
        fallback_reason="uncertain_intent",
    )
    calls = []
    await _service(llm)._ask(
        calls,
        AgentConfig(settings={}),
        "campaign-id",
        "seat-id",
        None,
        "decide",
        messages,
        tools,
        override_model="test-model",
        prompt_metadata=bundle.metadata("decide"),
    )
    assert len(captured) == 1
    assert len(calls) == 1
    return captured[0], calls[0]


def test_runtime_diagnostics_record_retry_count_and_reasons():
    async def run():
        llm = ScriptedLLM([{"text": "ok"}])
        calls = []
        await _service(llm)._ask(
            calls,
            AgentConfig(settings={}),
            "campaign-id",
            "seat-id",
            None,
            "decide",
            [{"role": "user", "content": "retry me"}],
            [],
            override_model="test-model",
            retry_count=2,
            retry_reasons=("unresolved_actions", "invalid_source"),
        )
        return calls[0]

    call = asyncio.run(run())

    assert call.diagnostics["retry_count"] == 2
    assert call.diagnostics["retry_reasons"] == ["unresolved_actions", "invalid_source"]


@pytest.mark.parametrize("prompt_version", ["role-context-v1", "role-context-v2"])
def test_legacy_path_reports_selection_not_applied_for_any_prompt_version(prompt_version):
    request, call = asyncio.run(_ask_legacy(
        prompt_version=prompt_version,
        messages=[
            {"role": "system", "content": "legacy system"},
            {"role": "user", "content": "legacy request"},
        ],
    ))

    assert call.diagnostics["assembly_path"] == "legacy"
    assert call.diagnostics["selection_applied"] is False


def test_legacy_path_result_does_not_depend_on_prompt_version():
    messages = [{"role": "user", "content": "legacy request"}]

    _, first = asyncio.run(_ask_legacy(prompt_version="role-context-v1", messages=messages))
    _, second = asyncio.run(_ask_legacy(prompt_version="role-context-v2", messages=messages))

    path_metadata = ("assembly_path", "selection_applied", "fallback_reason")
    assert tuple(first.diagnostics[key] for key in path_metadata) == tuple(
        second.diagnostics[key] for key in path_metadata
    )
    assert first.diagnostics["assembly_path"] == "legacy"
    assert first.diagnostics["selection_applied"] is False
    assert first.diagnostics["prompt_version"] != second.diagnostics["prompt_version"]


def test_runtime_sizes_match_the_serialized_llm_complete_call():
    messages = [
        {"role": "system", "content": "system"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "roll_check", "arguments": '{"dc": 12}'},
                }
            ],
        },
    ]
    tools = [
        {
            "type": "function",
            "function": {"name": "roll_check", "parameters": {"type": "object"}},
        }
    ]

    request, call = asyncio.run(_ask_legacy(
        prompt_version="role-context-v1",
        messages=messages,
        tools=tools,
    ))

    expected = message_sizes(request["messages"], request["tools"])
    actual = {key: call.diagnostics[key] for key in expected}
    assert actual == expected
