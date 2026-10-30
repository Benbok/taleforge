import argparse
import asyncio
import json

import pytest

from app.agents.llm import LLMReply, ScriptedLLM, ToolCall
from tests.eval import run


def options(target, *, save=False):
    return argparse.Namespace(n=1, cases="station_wait", save=save, output=str(target), concurrency=1)


def test_runner_records_usage_checks_and_protects_measurements(tmp_path, monkeypatch):
    reply = LLMReply(
        text="",
        tokens_in=123,
        tokens_cached=80,
        tokens_out=15,
        tool_calls=[
            ToolCall(
                "call",
                "submit_action",
                {
                    "source": "mundane",
                    "resolution": "automatic",
                    "effects": [{"kind": "wait"}],
                },
            )
        ],
    )
    provider = ScriptedLLM([reply])
    monkeypatch.setattr(run, "LiteLLMClient", lambda: provider)
    monkeypatch.setattr(run, "decide_model_for", lambda: "test/model")
    monkeypatch.setattr(run, "BASELINE", tmp_path / "baseline.json")
    target = tmp_path / "report.json"
    asyncio.run(run.evaluate(options(target)))
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["success_rate"] == 1
    assert report["rows"][0]["tokens_cached"] == 80
    assert report["mean_tokens_in"] == 123
    assert len(provider.requests) == 1
    with pytest.raises(ValueError, match="overwrite"):
        asyncio.run(run.evaluate(options(target)))
    assert len(provider.requests) == 1


def test_provider_failure_cannot_be_saved_as_the_baseline(tmp_path, monkeypatch):
    class Offline:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("not a measurement")

    monkeypatch.setattr(run, "LiteLLMClient", Offline)
    monkeypatch.setattr(run, "decide_model_for", lambda: "test/model")
    target = tmp_path / "baseline.json"
    monkeypatch.setattr(run, "BASELINE", target)
    with pytest.raises(RuntimeError, match="Baseline not saved"):
        asyncio.run(run.evaluate(options(target, save=True)))
    assert not target.exists()


def test_runner_counts_both_lore_requests(tmp_path, monkeypatch):
    from tests.test_prompting_slicers import context

    fixture = context()
    (tmp_path / "station.json").write_text(json.dumps(fixture), encoding="utf-8")
    provider = ScriptedLLM(
        [
            LLMReply(text='{"need_lore": ["laws:1"]}', tokens_in=100, tokens_cached=50),
            LLMReply(
                text='{"source": "mundane", "resolution": "automatic", "effects": [{"kind": "wait"}]}',
                tokens_in=120,
                tokens_cached=70,
            ),
        ]
    )
    monkeypatch.setattr(run, "FIXTURES", tmp_path)
    monkeypatch.setattr(run, "LiteLLMClient", lambda: provider)
    monkeypatch.setattr(run, "decide_model_for", lambda: "test/model")
    monkeypatch.setattr(run, "BASELINE", tmp_path / "baseline.json")
    target = tmp_path / "report.json"
    asyncio.run(run.evaluate(options(target)))
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["rows"][0]["attempts"] == 2
    assert report["mean_tokens_in"] == 220
    assert report["rows"][0]["tokens_cached"] == 120
    assert len(provider.requests) == 2
