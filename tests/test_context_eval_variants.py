from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_context_experiment_config_accepts_only_declared_variants():
    from tools.context_eval_variants import ExperimentConfig

    assert ExperimentConfig(kind="context", variants=("legacy", "v1", "revised")).variants == (
        "legacy",
        "v1",
        "revised",
    )
    with pytest.raises(ValueError, match="variant"):
        ExperimentConfig(kind="context", variants=("optimized",))


def test_package_capture_preserves_full_tool_protocol():
    from tools.context_eval_variants import package_for_variant

    source = {
        "messages": [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "request"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "call-1", "type": "function", "function": {"name": "resolve_attack", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call-1", "content": "success"},
        ],
        "tools": [{"function": {"name": "resolve_attack"}}],
    }
    legacy = package_for_variant("legacy", source)
    v1 = package_for_variant("v1", source)
    revised = package_for_variant("revised", source)

    for package in (legacy, v1, revised):
        assert package["messages"] == source["messages"]
        assert package["tools"] == source["tools"]
    source["messages"][-1]["content"] = "mutated"
    assert legacy["messages"][-1]["content"] == "success"


@pytest.mark.parametrize("kind,variants", [("context", ("legacy", "v1", "revised")), ("tools", ("full", "profile"))])
def test_real_child_dispatches_variants_and_compares_outcomes(kind, variants):
    from tools.context_eval_variants import ExperimentConfig
    from tools.eval_turn_efficiency import run_scripted

    case = {
        "id": "attack",
        "nodeid": "tests/test_context_eval_dispatch.py::test_received_inputs_match_measurements[attack]",
        "tags": ["mechanics"],
        "scope": "full_turn",
    }
    native = {**case, "id": "native", "nodeid": case["nodeid"].replace("[attack]", "[native]")}
    report = run_scripted([case, native], experiment=ExperimentConfig(kind, variants))
    assert not report["variant_errors"]
    assert not report["mechanical_mismatches"]
    rows = [report["variants"][variant]["cases"][0] for variant in variants]
    assert all(
        payload["exit_code"] == 0 and payload["summary"]["passed"] == 2 for payload in report["variants"].values()
    )
    assert all(row["status"] == "passed" and row["snapshot"] is not None for row in rows)
    assert all(row["measured_inputs"] for row in rows)
    assert rows[0]["measured_inputs"][0]["digest"] != rows[1]["measured_inputs"][0]["digest"]
    if kind == "tools":
        assert rows[0]["measured_inputs"][0]["tool_count"] > rows[1]["measured_inputs"][0]["tool_count"]
    else:
        assert all(row["assembler_calls"] >= 2 for row in rows)
        assert all(
            row["measured_inputs"][0]["tool_names"] == rows[0]["measured_inputs"][0]["tool_names"] for row in rows
        )


def test_historical_artifacts_match_recorded_git_blobs():
    import hashlib

    root = Path("tools/context_eval_history")
    provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    for filename, (_, blob) in provenance["source_blobs"].items():
        data = (root / filename).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == blob


@pytest.mark.parametrize("role", ["decide", "narrate", "voice_line", "review"])
def test_historical_assembly_recovers_full_request_from_split_inputs(monkeypatch, role):
    import asyncio

    from app.agents.master import resolution
    from tools.context_eval_variants import assemble_variant, historical_assembler

    values = dict(
        difficulty="normal",
        leveling=True,
        random_events=True,
        critical_checks=True,
        has_plot=False,
        max_calls=8,
        campaign_name="probe",
        style=None,
        brief="brief",
        excluded_themes="",
        public_intro="",
        secrets="private canon",
        pacing="",
        dc_scale="",
        audio="",
    )

    async def prompt_values(ctx, cfg):
        return values

    async def action_context(ctx):
        return "ACTION_REFS"

    monkeypatch.setattr(historical_assembler(), "master_prompt_values", prompt_values)
    monkeypatch.setattr(resolution, "action_context_prompt", action_context)
    inputs = {
        "request": "new request only",
        "history": "split history",
        "packet": "VOICE_PACKET",
        "resolution": "RESOLUTION",
        "legacy_messages": [
            {"role": "system", "content": "CURRENT_TEMPLATE_SENTINEL"},
            {"role": "user", "content": "DURABLE_MEMORY\nSCENE\nCHAT\nRESOLUTION\nnew request only"},
        ],
    }
    legacy = asyncio.run(assemble_variant("legacy", SimpleNamespace(), None, role=role, inputs=inputs))
    v1 = asyncio.run(assemble_variant("v1", SimpleNamespace(), None, role=role, inputs=inputs))
    assert legacy.messages[1]["content"] == inputs["legacy_messages"][1]["content"]
    assert "CURRENT_TEMPLATE_SENTINEL" not in legacy.messages[0]["content"]
    assert "DURABLE_MEMORY\nSCENE\nCHAT" in v1.messages[1]["content"]
    assert len(v1.messages) == 2
    if role == "decide":
        assert v1.blocks["actions"] == "ACTION_REFS"
        assert "RESOLUTION" not in v1.blocks["request"]
        assert v1.blocks["resolution"] == "RESOLUTION"
        uncertain = asyncio.run(
            assemble_variant("v1", SimpleNamespace(), None, role=role, inputs={**inputs, "uncertain": True})
        )
        assert uncertain.fallback_reason == "uncertain_intent"
        assert uncertain.messages == legacy.messages
    assert inputs["legacy_messages"][0]["content"] == "CURRENT_TEMPLATE_SENTINEL"


@pytest.mark.parametrize("changed_outcome", [False, True])
def test_context_run_scripted_passes_effective_variant_to_child_and_reports_it(tmp_path, changed_outcome):
    from tools import eval_turn_efficiency as runner
    from tools.context_eval_variants import ExperimentConfig

    case = {
        "id": "probe",
        "nodeid": "tests/test_turn_efficiency.py::test_paired_scripted_turn[attack]",
        "tags": ["mechanics"],
        "scope": "full_turn",
    }

    def execute(command, **options):
        env = options["env"]
        assert env["TALEFORGE_EVAL_EXPERIMENT"] == "context"
        variant = env["TALEFORGE_EVAL_CONTEXT_VARIANT"]
        Path(env["TALEFORGE_EVAL_RESULT"]).write_text(
            json.dumps(
                [
                    {
                        "nodeid": case["nodeid"],
                        "status": "passed",
                        "model_calls": {},
                        "fallback": 0,
                        "unknown_usage": 0,
                        "snapshot": {"hp": 9 if changed_outcome and variant == "revised" else 10},
                        "effective_context_variant": variant,
                        "context_package_digest": f"digest:{variant}",
                    }
                ]
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    report = runner.run_scripted(
        [case],
        execute=execute,
        experiment=ExperimentConfig(kind="context", variants=("legacy", "revised")),
    )

    assert set(report["variants"]) == {"legacy", "revised"}
    assert report["variants"]["legacy"]["cases"][0]["effective_context_variant"] == "legacy"
    assert report["variants"]["revised"]["cases"][0]["context_package_digest"] == "digest:revised"
    assert report["mechanical_mismatches"] == (["probe"] if changed_outcome else [])


def test_context_run_scripted_records_child_crash_as_failed_variant(tmp_path):
    from tools import eval_turn_efficiency as runner
    from tools.context_eval_variants import ExperimentConfig

    case = {
        "id": "probe",
        "nodeid": "tests/test_turn_efficiency.py::test_paired_scripted_turn[attack]",
        "tags": ["mechanics"],
        "scope": "full_turn",
    }

    def execute(command, **options):
        return SimpleNamespace(returncode=7, stdout="child failed", stderr="trace")

    report = runner.run_scripted(
        [case], execute=execute, experiment=ExperimentConfig(kind="context", variants=("revised",))
    )

    variant = report["variants"]["revised"]
    assert variant["exit_code"] == 7
    assert variant["summary"]["failed"] == 1
    assert variant["cases"][0]["failure_phase"] == "collection"


def test_identity_normalization_does_not_change_mechanical_values():
    from tools.eval_turn_efficiency import normalize_identities

    assert normalize_identities(
        '"ch_0123456789abcdef": {"hp": 12, "target": "abcde123-1234-4321-1234-123456789abc"}'
    ) == ('"<instance>": {"hp": 12, "target": "<uuid>"}')


def test_actual_ask_preserves_assistant_calls_and_tool_results():
    import asyncio

    from app.agents.llm import ScriptedLLM
    from app.agents.master.turn import TurnMixin

    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "request"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "get_scene", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": '{"ok": true}'},
    ]
    tools = [{"type": "function", "function": {"name": "get_scene", "parameters": {"type": "object"}}}]
    client = ScriptedLLM([{"text": "done"}])
    calls = []
    asyncio.run(
        TurnMixin._ask(
            SimpleNamespace(llm=client),
            calls,
            SimpleNamespace(temperature=0.2, settings={}),
            "campaign",
            "seat",
            None,
            "decide",
            messages,
            tools,
        )
    )
    assert client.requests[0]["messages"] == messages
    assert client.requests[0]["tools"] == tools
    assert calls[0].diagnostics["blocks"]["message_2_assistant_tool_calls"]["utf8_bytes"] > 0


def test_quality_reports_historical_private_access_without_erasing_required_facts():
    from tools.context_eval_variants import context_quality

    case = {
        "requests": [{"text": "player asks"}],
        "required_facts_by_role": {"decide": ["request", "old promise"], "narrate": ["public outcome"]},
        "forbidden_facts_by_role": {"narrate": ["private motive"]},
    }
    quality = context_quality(
        case,
        [
            {"purpose": "decide", "messages": [{"content": "player asks"}]},
            {"purpose": "narrate", "messages": [{"content": "public outcome private motive"}]},
        ],
    )
    assert quality["decide"]["missing_required"] == ["old promise"]
    assert quality["narrate"]["present_forbidden"] == ["private motive"]
    assert quality["narrate"]["missing_required"] == []
