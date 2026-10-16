"""Offline evaluation safety and real paired master turns."""

# ruff: noqa: F811 -- shared integration fixtures
import asyncio
import importlib
import os
from pathlib import Path

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


def test_manifest_contains_real_mechanical_cases():
    cases = runner().load_cases(Path("tests/fixtures/turn_efficiency.json"))
    assert len(cases) >= 20
    assert len({case["id"] for case in cases}) == len(cases)
    for case in cases:
        assert Path(case["nodeid"].split("::")[0]).is_file()
    assert {
        "attack",
        "miss",
        "critical",
        "move_attack",
        "spell",
        "resource_denial",
        "aoe",
        "reaction",
        "speech",
        "social",
        "search_found",
        "search_empty",
        "container",
        "preparation",
        "pickup",
        "transfer",
        "unknown_target",
        "unparsed",
        "multipart",
        "two_heroes",
        "invalid_ref",
        "rollback",
        "hidden_fact",
        "split_party",
        "transition",
    } <= {tag for case in cases for tag in case["tags"]}


def test_scripted_children_strip_inherited_live_mode(monkeypatch):
    import json
    from types import SimpleNamespace

    monkeypatch.setenv("TALEFORGE_EVAL_LIVE", "1")
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://must-not-touch")
    seen = []

    def execute(command, **options):
        env = options["env"]
        seen.append(env)
        assert "TALEFORGE_EVAL_LIVE" not in env and "TEST_DATABASE_URL" not in env
        Path(env["TALEFORGE_EVAL_RESULT"]).write_text(
            json.dumps(
                [
                    {
                        "nodeid": "tests/test_turn_efficiency.py::test_paired_scripted_turn[attack]",
                        "status": "passed",
                        "model_calls": {},
                        "fallback": 0,
                        "unknown_usage": 0,
                        "snapshot": {},
                    }
                ]
            )
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    case = runner().load_cases(Path("tests/fixtures/turn_efficiency.json"))[0]
    report = runner().run_scripted([case], execute=execute)
    assert len(seen) == 2 and report["live_performed"] is False


def test_live_pair_stops_before_second_variant_if_reservation_wont_fit(tmp_path):
    import json
    from types import SimpleNamespace

    calls = []

    def execute(command, **options):
        env = options["env"]
        calls.append(command)
        assert env["TALEFORGE_EVAL_LIVE"] == "1"
        Path(env["TALEFORGE_EVAL_RESULT"]).write_text("[]")
        Path(env["TALEFORGE_EVAL_JOURNAL"]).write_text(
            json.dumps(
                [
                    {
                        "cost_usd": 0.07,
                        "cost_known": True,
                        "tokens_in": 10,
                        "tokens_out": 2,
                        "tokens_cached": None,
                        "failed": False,
                    }
                ]
            )
        )
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    case = runner().load_cases(Path("tests/fixtures/turn_efficiency.json"))[0]
    report = runner().run_scripted(
        [case],
        execute=execute,
        live_options={
            "budget": 0.1,
            "reserve": 0.06,
            "model": "test/model",
            "campaign": "isolated-label",
            "journal_dir": tmp_path,
        },
    )
    assert len(calls) == 1
    assert report["known_cost_usd"] == 0.07
    assert report["variants"]["optimized"]["status"] == "budget_not_admitted"


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


@pytest.mark.parametrize("scenario", ["attack", "miss", "critical", "native", "speech", "unparsed"])
def test_paired_scripted_turn(game_client, admin_g, llm, dice, settings, monkeypatch, scenario):
    """Same scene, dice and purpose-aware scripted model in both flag configurations."""
    from app.db.models import Campaign, Entity, Event, InventoryItem, LlmCall, MasterTurn
    from tests.game import party, run
    from tests.test_combat import _setup
    from tests.test_master import act, rows

    optimized = os.environ.get("TALEFORGE_EVAL_VARIANT") == "optimized"
    live = os.environ.get("TALEFORGE_EVAL_LIVE") == "1"
    if live and scenario != "attack":
        pytest.fail("The live driver only supports the isolated attack case")
    campaign, (player,), hero = party(game_client, admin_g)
    cid = campaign["id"]

    async def flags(s):
        c = await s.get(Campaign, cid)
        c.settings = {
            **c.settings,
            "llm_optimization": dict.fromkeys(
                ("action_refs", "tool_profiles", "role_context", "early_finish", "compact_voice", "compact_review"),
                optimized,
            ),
        }
        await s.commit()

    run(settings, flags)
    enemy = None
    if scenario in {"attack", "miss", "critical"}:
        enemy = _setup(settings, cid, hero["id"], "creature.goblin", zone="melee", first="hero", hp=30)
        weapon = next(
            i.id
            for i in rows(settings, InventoryItem, InventoryItem.character_id == hero["id"])
            if i.item_template_id == "item.longsword"
        )
        parsed = {"actions": [{"index": 0, "verb": "attack", "target_id": enemy, "instrument_id": weapon}]}
        dice += {"attack": [18, 5], "miss": [2], "critical": [20, 5, 5]}[scenario]
    elif scenario == "native":
        parsed = {"actions": [{"index": 0, "verb": "interact", "summary": "Wave"}]}
    elif scenario == "speech":
        parsed = {"kind": "speech", "actions": []}
    else:
        parsed = {"kind": "custom", "actions": []}

    original = llm.complete
    decided = False
    live_complete = None
    if live:
        live_complete = runner().isolated_live_completion(monkeypatch)

    async def complete(messages, **kwargs):
        nonlocal decided
        names = {tool["function"]["name"] for tool in kwargs.get("tools") or []}
        if "submit_intent" in names:
            reply = {"tool_calls": [("submit_intent", parsed)]}
        elif live_complete is not None:
            return await live_complete(messages, **kwargs)
        elif names and scenario == "native" and not decided:
            decided = True
            reply = {"tool_calls": [("auto_success", {"character_id": hero["id"], "reason": "wave"})]}
        else:
            reply = {"text": "Подтверждённый исход описан."}
        llm.replies.insert(0, reply)
        return await original(messages, **kwargs)

    llm.complete = complete
    text = act(game_client, player, cid, "Привет!" if scenario == "speech" else "Атакую гоблина длинным мечом.")
    assert text["kind"] == "narration"
    (turn,) = rows(settings, MasterTurn, MasterTurn.campaign_id == cid)
    assert turn.status == "done"
    decisions = rows(settings, LlmCall, LlmCall.turn_id == turn.id, LlmCall.purpose == "decide")
    if scenario in {"attack", "miss", "critical"}:
        if not live:
            # Production is always-on; evaluator variants are isolated
            # labels and cannot disable the runtime behavior.
            assert len(decisions) == 0
        attacks = rows(
            settings, Event, Event.turn_id == turn.id, Event.tool == "resolve_attack", Event.actor_id == hero["id"]
        )
        assert len(attacks) == 1
        assert attacks[0].payload["hit"] is (scenario != "miss")
        hp = rows(settings, Entity, Entity.id == enemy)[0].state["hp"]
        assert hp == (30 if scenario == "miss" else 17 if scenario == "critical" else 22)
    elif scenario == "native":
        assert len(decisions) == 1
        assert len(rows(settings, Event, Event.turn_id == turn.id, Event.tool == "auto_success")) == 1
    else:
        assert len(decisions) >= 1
    if scenario not in {"speech", "unparsed"}:
        assert not rows(settings, Event, Event.turn_id == turn.id, Event.tool == "cancel_action")
