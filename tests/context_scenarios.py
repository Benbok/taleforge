"""Executable context-quality scenarios for the real prompt assembler.

The scenario manifest describes behavior, while this module turns each named
fact and expected outcome into a production ``ContextFact`` and checks the
serialized request.  Full world-tool outcomes remain covered by the paired
turn cases; this layer specifically prevents a manifest from becoming a
schema-only checklist.
"""

from __future__ import annotations

from app.agents.master.context_selection import ContextFact
from app.agents.master.prompt_context import build_prompt_bundle
from app.core.llm_diagnostics import message_sizes
from app.db.models import AgentConfig


def scenario_facts(scenario: dict) -> tuple[ContextFact, ...]:
    required = list(dict.fromkeys([*scenario["required_facts"], *scenario["expected_outcomes"]]))
    return tuple(
        ContextFact(
            key=f"scenario:{scenario['id']}:{name}",
            section="scenario",
            text=f"SCENARIO_FACT:{name}",
            subjects=frozenset({"scenario"}),
            dependencies=frozenset(),
            audience=frozenset({"master"}),
            mandatory=name in scenario["required_facts"],
        )
        for name in required
    ) + tuple(
        ContextFact(
            key=f"scenario:{scenario['id']}:forbidden:{name}",
            section="scenario",
            text=f"FORBIDDEN_FACT:{name}",
            subjects=frozenset({"unrelated"}),
            dependencies=frozenset(),
            audience=frozenset({"master"}),
        )
        for name in scenario["forbidden_facts"]
    )


async def execute_context_scenario(ctx, scenario: dict) -> dict:
    """Run one manifest scenario through the production decide assembler."""
    bundle = await build_prompt_bundle(
        ctx,
        AgentConfig(settings={}),
        role="decide",
        inputs={
            "request": scenario["requests"][0],
            "context_facts": scenario_facts(scenario),
            "subjects": {"scenario"},
            "uncertain": scenario["id"] == "unknown_parser",
            "legacy_messages": [
                {"role": "system", "content": "legacy"},
                {"role": "user", "content": "legacy should not be sent"},
            ],
        },
    )
    rendered = "\n".join(message.get("content") or "" for message in bundle.messages)
    required = [f"SCENARIO_FACT:{name}" for name in scenario["required_facts"]]
    outcomes = [f"SCENARIO_FACT:{name}" for name in scenario["expected_outcomes"]]
    forbidden = [f"FORBIDDEN_FACT:{name}" for name in scenario["forbidden_facts"]]
    assert all(marker in rendered for marker in (*required, *outcomes))
    assert all(marker not in rendered for marker in forbidden)
    assert bundle.assembly_path in {"selected", "expanded"}
    assert bundle.selection_applied is True
    baseline_text = "\n".join(fact.text for fact in scenario_facts(scenario))
    baseline = await build_prompt_bundle(
        ctx,
        AgentConfig(settings={}),
        role="decide",
        inputs={
            "request": baseline_text,
            "uncertain": True,
            "legacy_messages": [
                {"role": "system", "content": "legacy"},
                {"role": "user", "content": baseline_text},
            ],
        },
    )
    baseline_rendered = "\n".join(message.get("content") or "" for message in baseline.messages)
    assert all(marker in baseline_rendered for marker in (*required, *outcomes))
    assert all(marker in baseline_rendered for marker in forbidden)
    revised_size = message_sizes(bundle.messages, [])
    baseline_size = message_sizes(baseline.messages, [])
    return {
        "id": scenario["id"],
        "required_facts": required,
        "expected_outcomes": outcomes,
        "forbidden_facts": forbidden,
        "assembly_path": bundle.assembly_path,
        "baseline_assembly_path": baseline.assembly_path,
        "revised_estimated_tokens": revised_size["tools"]["estimated_tokens"]
        + sum(block["estimated_tokens"] for block in revised_size["blocks"].values()),
        "baseline_estimated_tokens": baseline_size["tools"]["estimated_tokens"]
        + sum(block["estimated_tokens"] for block in baseline_size["blocks"].values()),
    }
