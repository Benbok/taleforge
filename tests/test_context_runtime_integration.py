"""Runtime assertions for context metadata attached to real LLM calls."""

# Fixtures imported from test_master intentionally share names with test args.
# ruff: noqa: F811

from __future__ import annotations

import asyncio

import pytest

from app.agents.llm import ScriptedLLM
from app.agents.master.prompt_context import PromptBundle
from app.agents.master.service import MasterService
from app.core.llm_diagnostics import message_sizes, tool_metrics
from app.db.models import AgentConfig
from tests.test_master import admin_g, dice, game_client, llm  # noqa: F401


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


def test_tool_metrics_are_content_free_and_include_each_schema_size():
    tools = [
        {"type": "function", "function": {"name": "inspect", "description": "read"}},
        {"type": "function", "function": {"name": "move", "description": "act"}},
    ]
    metrics = tool_metrics(tools, "exploration")
    assert metrics["tool_profile"] == "exploration"
    assert metrics["tool_count"] == 2
    assert set(metrics["tool_schema_sizes"]) == {"inspect", "move"}
    assert metrics["tool_schema_total"]["utf8_bytes"] > 0
    assert all("description" not in size for size in metrics["tool_schema_sizes"].values())


def test_production_decide_request_selects_snapshot_facts(game_client, admin_g, llm, monkeypatch):
    from app.agents.master import context_snapshot
    from app.agents.master.context_selection import ContextFact
    from tests.game import party
    from tests.test_master import DONE, act

    campaign, (player,), hero = party(game_client, admin_g)
    hero_id = hero["id"]
    facts = (
        ContextFact(
            key="npc:current",
            section="targets",
            text="CURRENT_NPC_MARKER",
            subjects=frozenset({hero_id}),
            dependencies=frozenset(),
            audience=frozenset({"master"}),
        ),
        ContextFact(
            key="npc:distant",
            section="targets",
            text="DISTANT_NPC_MARKER",
            subjects=frozenset({"far-away-npc"}),
            dependencies=frozenset(),
            audience=frozenset({"master"}),
        ),
        ContextFact(
            key="reaction:current",
            section="reactions",
            text="ACTIVE_REACTION_MARKER",
            subjects=frozenset({hero_id}),
            dependencies=frozenset(),
            audience=frozenset({"master"}),
        ),
        ContextFact(
            key="promise:old",
            section="requests",
            text="OLD_PROMISE_MARKER",
            subjects=frozenset({hero_id}),
            dependencies=frozenset(),
            audience=frozenset({"master"}),
            mandatory=True,
        ),
        ContextFact(
            key="rule:current",
            section="rules",
            text="RULE_MARKER",
            subjects=frozenset(),
            dependencies=frozenset(),
            audience=frozenset({"master"}),
        ),
        ContextFact(
            key="action_ref:current",
            section="requests",
            text="ACTION_REF_MARKER",
            subjects=frozenset({hero_id}),
            dependencies=frozenset(),
            audience=frozenset({"master"}),
            mandatory=True,
        ),
    )
    monkeypatch.setattr(context_snapshot, "collect_context_snapshot", lambda *args, **kwargs: facts)
    llm.replies += [
        {"tool_calls": [("submit_intent", {"actions": [{"index": 0, "verb": "interact", "summary": "Wave"}]})]},
        {"tool_calls": [("auto_success", {"character_id": hero_id, "reason": "wave"})]},
        DONE,
        {"text": "Ты машешь рукой."},
        {"text": "Ты машешь рукой."},
    ]

    assert act(game_client, player, campaign["id"], "Машу рукой")["kind"] == "narration"
    decide_request = llm.requests[1]["messages"][1]["content"]
    assert "CURRENT_NPC_MARKER" in decide_request
    assert "ACTIVE_REACTION_MARKER" in decide_request
    assert "OLD_PROMISE_MARKER" in decide_request
    assert "RULE_MARKER" in decide_request
    assert "ACTION_REF_MARKER" in decide_request
    assert "DISTANT_NPC_MARKER" not in decide_request


def test_production_narrate_request_uses_audience_safe_snapshot(game_client, admin_g, llm, monkeypatch):
    from app.agents.master import context_snapshot
    from app.agents.master.context_selection import ContextFact
    from tests.game import party
    from tests.test_master import DONE, act

    campaign, (player,), hero = party(game_client, admin_g)
    hero_id = hero["id"]
    facts = (
        ContextFact(
            "outcome",
            "outcomes",
            "NARRATION_PUBLIC_OUTCOME_MARKER",
            frozenset({hero_id}),
            frozenset(),
            frozenset({"party"}),
        ),
        ContextFact(
            "relationship",
            "relationships",
            "NARRATION_PUBLIC_RELATIONSHIP_MARKER",
            frozenset({hero_id}),
            frozenset(),
            frozenset({"party"}),
        ),
        ContextFact(
            "promise",
            "promises",
            "NARRATION_PUBLIC_PROMISE_MARKER",
            frozenset({hero_id}),
            frozenset(),
            frozenset({"party"}),
        ),
        ContextFact(
            "motive",
            "motives",
            "NARRATION_PRIVATE_MOTIVE_MARKER",
            frozenset({hero_id}),
            frozenset(),
            frozenset({"master"}),
        ),
    )

    def snapshot(ctx, *args, **kwargs):
        return facts if ctx.narration_viewer_ids is not None else ()

    monkeypatch.setattr(context_snapshot, "collect_context_snapshot", snapshot)
    llm.replies += [
        {"tool_calls": [("submit_intent", {"actions": [{"index": 0, "verb": "interact", "summary": "Wave"}]})]},
        {"tool_calls": [("auto_success", {"character_id": hero_id, "reason": "wave"})]},
        DONE,
        {"text": "Ты машешь рукой."},
        {"text": "Ты машешь рукой."},
    ]

    assert act(game_client, player, campaign["id"], "Машу рукой")["kind"] == "narration"
    narration_requests = [
        request["messages"][1]["content"]
        for request in llm.requests
        if "NARRATION_PUBLIC_OUTCOME_MARKER" in request["messages"][1]["content"]
    ]
    assert narration_requests
    assert all("NARRATION_PRIVATE_MOTIVE_MARKER" not in request for request in narration_requests)
    assert all(
        marker in narration_requests[0]
        for marker in (
            "NARRATION_PUBLIC_OUTCOME_MARKER",
            "NARRATION_PUBLIC_RELATIONSHIP_MARKER",
            "NARRATION_PUBLIC_PROMISE_MARKER",
        )
    )
