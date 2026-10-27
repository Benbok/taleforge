"""Offline evaluation safety and real paired master turns."""

# ruff: noqa: F811 -- shared integration fixtures
import asyncio
import importlib

import pytest

from app.agents.llm import LLMReply
from tests.test_master import admin_g, dice, game_client, llm  # noqa: F401


def runner():
    try:
        return importlib.import_module("tools.eval_turn_efficiency")
    except ModuleNotFoundError:
        pytest.fail("The efficiency evaluation runner has not been implemented")


def test_context_variant_is_evaluator_only():
    with pytest.raises(ValueError, match="context variant"):
        runner().validate_context_options("context", "unknown")
    assert runner().validate_context_options("context", "revised") == {
        "experiment": "context",
        "context_variant": "revised",
    }


@pytest.mark.parametrize("bad", [{}, {"version": 1, "cases": []}, {"version": 1, "cases": [{"id": "x"}]}])
def test_malformed_cases_rejected(bad):
    with pytest.raises(ValueError):
        runner().validate_cases(bad)


@pytest.mark.parametrize("budget", [None, 0, -1, float("nan"), float("inf")])
def test_live_requires_positive_explicit_budget(budget):
    with pytest.raises(ValueError, match="budget"):
        runner().validate_live("campaign", budget, isolated=False)


def test_live_requires_isolation_even_with_budget():
    with pytest.raises(ValueError, match="isolated"):
        runner().validate_live("campaign", 1, isolated=False)


def test_budget_retains_paid_response_before_stopping():
    async def go():
        guard = runner().BudgetGuard(0.01)

        async def paid():
            return LLMReply("ok", cost=0.02, cost_known=True, tokens_in=17, tokens_out=3)

        reply = await guard.complete(paid)
        assert reply.tokens_in == 17
        assert guard.records == [
            {
                "cost_usd": 0.02,
                "cost_known": True,
                "tokens_in": 17,
                "tokens_out": 3,
                "tokens_cached": None,
                "failed": False,
                "duration_ms": guard.records[0]["duration_ms"],
                "purpose": "unknown",
            }
        ]
        assert guard.records[0]["duration_ms"] >= 0
        with pytest.raises(runner().BudgetExceeded):
            await guard.complete(paid)
        assert len(guard.records) == 1

    asyncio.run(go())


def test_budget_reserves_next_request_before_admission(tmp_path):
    async def go():
        journal = tmp_path / "usage.json"
        guard = runner().BudgetGuard(0.10, request_reserve_usd=0.06, journal=journal)

        async def paid():
            return LLMReply("ok", cost=0.05, cost_known=True, tokens_in=17)

        await guard.complete(paid)
        with pytest.raises(runner().BudgetExceeded):
            await guard.complete(paid)
        import json

        assert json.loads(journal.read_text())[0]["tokens_in"] == 17

    asyncio.run(go())


def test_unknown_price_stops_following_requests_and_failure_is_reported():
    async def go():
        guard = runner().BudgetGuard(1)

        async def unknown():
            return LLMReply("ok", tokens_in=7)

        await guard.complete(unknown)
        with pytest.raises(runner().BudgetExceeded):
            await guard.complete(unknown)
        assert guard.records[0]["cost_known"] is False

        async def failure():
            raise RuntimeError("provider")

        guard = runner().BudgetGuard(1)
        with pytest.raises(RuntimeError):
            await guard.complete(failure)
        assert guard.records[0]["failed"] is True
        with pytest.raises(runner().BudgetExceeded):
            await guard.complete(unknown)

    asyncio.run(go())


def test_report_retains_failed_fallback_and_unknown_usage():
    rows = [
        {
            "id": "case",
            "status": "failed",
            "model_calls": {"decide": 2},
            "fallback": 1,
            "unknown_usage": 2,
            "snapshot": {},
        }
    ]
    report = runner().summarize(rows)
    assert report["failed"] == 1 and report["fallback"] == 1 and report["unknown_usage"] == 2
    assert report["cost_usd"] is None and report["cache_hit_rate"] is None
    assert report["literary_quality"] == "not_measured"


def test_live_adapter_uses_explicit_model_no_retry_and_preserves_usage(monkeypatch, tmp_path):
    import litellm

    module = runner()
    captured = []

    async def provider(**kwargs):
        captured.append(kwargs)
        return litellm.ModelResponse(
            model="test/not-priced",
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Confirmed."},
                    "finish_reason": "stop",
                }
            ],
            usage={"prompt_tokens": 17, "completion_tokens": 3, "total_tokens": 20},
        )

    monkeypatch.setattr(module, "_LIVE_PROVIDER", provider)
    for key, value in {
        "LIVE": "1",
        "BUDGET": "1",
        "RESERVE": "0.1",
        "MODEL": "test/not-priced",
        "RUN_LABEL": "isolated",
        "JOURNAL": str(tmp_path / "usage.json"),
    }.items():
        monkeypatch.setenv("TALEFORGE_EVAL_" + key, value)
    complete = module.isolated_live_completion(monkeypatch)

    async def go():
        with pytest.raises(module.BudgetExceeded, match="ticket"):
            await litellm.acompletion(model="test/not-priced", messages=[])
        reply = await complete([{"role": "user", "content": "Test"}], model="ignored", max_tokens=8192)
        assert reply.tokens_in == 17
        with pytest.raises(module.BudgetExceeded):
            await complete([{"role": "user", "content": "Test"}], model="ignored")

    asyncio.run(go())
    assert len(captured) == 1
    assert captured[0]["model"] == "test/not-priced" and captured[0]["num_retries"] == 0
    assert captured[0]["max_tokens"] == 1024


def test_live_summary_reports_actual_tokens_latency_and_unknown_cost():
    report = runner().live_usage_summary(
        [
            {
                "cost_usd": 0.02,
                "cost_known": True,
                "tokens_in": 17,
                "tokens_out": 3,
                "tokens_cached": 5,
                "duration_ms": 100,
                "failed": False,
            },
            {
                "cost_usd": None,
                "cost_known": False,
                "tokens_in": None,
                "tokens_out": None,
                "tokens_cached": None,
                "duration_ms": 300,
                "failed": True,
            },
        ]
    )
    assert report["cost_usd"] is None and report["known_cost_usd"] == 0.02
    assert report["tokens_in"] == 17 and report["tokens_cached"] == 5
    assert report["request_latency_ms"] == {"samples": 2, "p50": 100, "p95": 300}


@pytest.mark.parametrize("cost", [-1, float("nan"), float("inf")])
def test_invalid_reported_price_cannot_bypass_budget(cost):
    async def go():
        guard = runner().BudgetGuard(1)

        async def invalid():
            return LLMReply("ok", cost=cost, cost_known=True)

        await guard.complete(invalid)
        assert guard.records[0]["cost_known"] is False
        with pytest.raises(runner().BudgetExceeded):
            await guard.complete(invalid)

    asyncio.run(go())
