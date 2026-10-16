"""Replay real pytest mechanics in isolated SQLite worlds; never infer live savings.

Scripted: python -m tools.eval_turn_efficiency --mode scripted --cases
tests/fixtures/turn_efficiency.json --output report.json

Live supports the isolated attack case, rebuilding the same disposable SQLite
world for each flag variant. --campaign is a run label, never a production lookup.
It requires an explicit model, budget, and conservative per-request reservation.
The parser and dice remain fixed; decision and narration use the real provider.
A response can exceed its reservation: only a provider-side hard cap can prevent
that overrun. The guard retains usage before stopping any following requests.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.context_eval_variants import ExperimentConfig, assemble_variant, effective_config, package_for_variant

ROOT = Path(__file__).resolve().parents[1]


def validate_context_options(experiment: str, context_variant: str) -> dict[str, str]:
    """Validate comparison labels accepted only by the offline evaluator."""
    if experiment not in {"context", "tools", "product"}:
        raise ValueError("experiment must be context, tools or product")
    allowed = {"legacy", "v1", "revised", "all"} if experiment == "context" else {"revised"}
    if experiment == "product":
        allowed = {"legacy", "optimized"}
    if context_variant not in allowed:
        raise ValueError("unknown context variant")
    return {"experiment": experiment, "context_variant": context_variant}


def validate_context_cases(document: object) -> list[dict]:
    if not isinstance(document, dict) or document.get("version") != 2:
        raise ValueError("context fixture version must be 2")
    scenarios = document.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("context fixture requires scenarios")
    required = {
        "id",
        "fixture",
        "requests",
        "parser_script",
        "model_script",
        "dice",
        "required_facts_by_role",
        "forbidden_facts_by_role",
        "expected_world",
        "rubric",
    }
    result = []
    seen = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict) or not required <= scenario.keys() or not scenario["id"]:
            raise ValueError("context scenario is incomplete")
        if scenario["id"] in seen:
            raise ValueError("duplicate context scenario id")
        seen.add(scenario["id"])
        result.append(scenario)
    return result


_RESULTS: dict[str, dict] = {}
_LIVE_PROVIDER = None
_PURPOSE = ContextVar("efficiency_purpose", default="unknown")
_PROVIDER_TICKET = ContextVar("efficiency_provider_ticket", default=None)


class BudgetExceeded(RuntimeError):
    """No new paid request is admissible."""


def validate_live(campaign: str | None, budget: float | None, *, isolated: bool) -> None:
    if budget is None or not math.isfinite(budget) or budget <= 0:
        raise ValueError("live requires an explicit positive finite budget (--max-cost-usd)")
    if not campaign or not isolated:
        raise ValueError("live requires an isolated test campaign and explicit isolation acknowledgement")


class BudgetGuard:
    """Serial admission and metadata retention; unknown billing stops further calls."""

    def __init__(self, max_cost_usd: float, *, request_reserve_usd: float = 0, journal: Path | None = None):
        validate_live("driver", max_cost_usd, isolated=True)
        self.limit = max_cost_usd
        self.records: list[dict] = []
        self._lock = asyncio.Lock()
        if not math.isfinite(request_reserve_usd) or not 0 <= request_reserve_usd <= max_cost_usd:
            raise ValueError("request reservation must be finite and fit the budget")
        self.reserve = request_reserve_usd
        self.journal = journal

    def _record(self, row):
        self.records.append(row)
        if self.journal:
            pending = self.journal.with_suffix(".pending")
            pending.write_text(json.dumps(self.records, allow_nan=False), encoding="utf-8")
            pending.replace(self.journal)

    async def complete(self, operation):
        async with self._lock:
            spent = sum(row["cost_usd"] or 0 for row in self.records)
            if (
                spent >= self.limit
                or spent + self.reserve > self.limit
                or any(not row["cost_known"] for row in self.records)
                or (self.reserve and any((row["cost_usd"] or 0) > self.reserve for row in self.records))
            ):
                raise BudgetExceeded("budget exhausted or previous response price unknown")
            started = time.monotonic()
            try:
                reply = await operation()
            except BaseException:
                # An interrupted/failed provider request can still have been billed.
                self._record(
                    {
                        "cost_usd": None,
                        "cost_known": False,
                        "tokens_in": None,
                        "tokens_out": None,
                        "tokens_cached": None,
                        "failed": True,
                        "duration_ms": round((time.monotonic() - started) * 1000),
                        "purpose": _PURPOSE.get(),
                    }
                )
                raise
            price_known = bool(
                reply.cost_known
                and isinstance(reply.cost, (int, float))
                and math.isfinite(reply.cost)
                and reply.cost >= 0
            )
            self._record(
                {
                    "cost_usd": reply.cost if price_known else None,
                    "cost_known": price_known,
                    "tokens_in": reply.tokens_in,
                    "tokens_out": reply.tokens_out,
                    "tokens_cached": reply.tokens_cached,
                    "failed": False,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "purpose": _PURPOSE.get(),
                }
            )
            return reply


def isolated_live_completion(monkeypatch):
    """Explicit live child only; ordinary pytest retains the global provider block."""
    import litellm

    from app.agents import llm as llm_module

    if os.environ.get("TALEFORGE_EVAL_LIVE") != "1" or _LIVE_PROVIDER is None:
        raise ValueError("live provider requires the explicitly admitted isolated CLI child")
    budget = float(os.environ["TALEFORGE_EVAL_BUDGET"])
    reserve = float(os.environ["TALEFORGE_EVAL_RESERVE"])
    validate_live(os.environ.get("TALEFORGE_EVAL_RUN_LABEL"), budget, isolated=True)

    async def no_provider_retry(**kwargs):
        ticket = _PROVIDER_TICKET.get()
        if ticket is None or not ticket["unused"]:
            raise BudgetExceeded("provider request has no unused budget admission ticket")
        ticket["unused"] = False
        return await _LIVE_PROVIDER(**{**kwargs, "num_retries": 0})

    async def once(operation):
        return await operation()

    monkeypatch.setattr(litellm, "acompletion", no_provider_retry)
    monkeypatch.setattr(llm_module, "_with_retry", once)
    client = llm_module.LiteLLMClient()
    guard = BudgetGuard(budget, request_reserve_usd=reserve, journal=Path(os.environ["TALEFORGE_EVAL_JOURNAL"]))

    async def complete(messages, **kwargs):
        kwargs["model"] = os.environ["TALEFORGE_EVAL_MODEL"]
        kwargs["max_tokens"] = min(kwargs.get("max_tokens", 1024), 1024)
        # Use the explicitly selected provider without any fixture-specific endpoint.
        kwargs["api_base"] = None

        async def operation():
            token = _PROVIDER_TICKET.set({"unused": True})
            try:
                return await client.complete(messages, **kwargs)
            finally:
                _PROVIDER_TICKET.reset(token)

        return await guard.complete(operation)

    return complete


def pytest_configure(config):
    global _LIVE_PROVIDER
    if os.environ.get("TALEFORGE_EVAL_LIVE") == "1":
        import litellm

        _LIVE_PROVIDER = litellm.acompletion


def validate_cases(document: object) -> list[dict]:
    if not isinstance(document, dict) or set(document) != {"version", "cases"} or document["version"] != 1:
        raise ValueError("case document must contain version=1 and cases")
    cases = document["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a nonempty list")
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "nodeid", "tags", "scope"}:
            raise ValueError("each case requires id, nodeid, tags and scope")
        if not isinstance(case["id"], str) or not re.fullmatch(r"[a-z][a-z0-9_]*", case["id"]):
            raise ValueError("invalid case id")
        if case["id"] in seen:
            raise ValueError("duplicate case id")
        seen.add(case["id"])
        node = case["nodeid"]
        if not isinstance(node, str) or not re.fullmatch(
            r"tests/test_[a-z0-9_]+\.py::test_[a-z0-9_]+(?:\[[^\]\r\n]+\])?", node
        ):
            raise ValueError("case must reference a single test node under tests/")
        if node.startswith("tests/test_turn_efficiency.py::") and not node.startswith(
            "tests/test_turn_efficiency.py::test_paired_scripted_turn["
        ):
            raise ValueError("evaluation cannot recursively execute runner tests")
        if case["scope"] not in {"mechanics", "full_turn", "visibility"}:
            raise ValueError("invalid case scope")
        if (
            not isinstance(case["tags"], list)
            or not case["tags"]
            or any(not isinstance(tag, str) or not tag for tag in case["tags"])
        ):
            raise ValueError("case tags must be nonempty strings")
        if not (ROOT / node.split("::")[0]).is_file():
            raise ValueError("case fixture file does not exist")
    return cases


def load_cases(path: Path) -> list[dict]:
    return validate_cases(json.loads(path.read_text(encoding="utf-8")))


def summarize(rows: list[dict]) -> dict:
    calls = Counter()
    sizes_by_role = {}
    for row in rows:
        calls.update(row.get("model_calls", {}))
        for packet in row.get("measured_inputs", []) + row.get("parse_inputs", []):
            sizes = packet["message_sizes"]
            totals = sizes_by_role.setdefault(
                packet["purpose"],
                {
                    "calls": 0,
                    "message_chars": 0,
                    "message_utf8_bytes": 0,
                    "message_estimated_tokens": 0,
                    "tool_chars": 0,
                    "tool_utf8_bytes": 0,
                    "tool_estimated_tokens": 0,
                },
            )
            totals["calls"] += 1
            for metric in ("chars", "utf8_bytes", "estimated_tokens"):
                totals["message_" + metric] += sum(block[metric] for block in sizes["blocks"].values())
                totals["tool_" + metric] += sizes["tools"][metric]
    return {
        "cases": len(rows),
        "passed": sum(row["status"] == "passed" for row in rows),
        "failed": sum(row["status"] == "failed" for row in rows),
        "skipped": sum(row["status"] == "skipped" for row in rows),
        "model_calls": dict(sorted(calls.items())),
        "fallback": sum(row.get("fallback", 0) for row in rows),
        "unknown_usage": sum(row.get("unknown_usage", 0) for row in rows),
        "cost_usd": None,
        "cache_hit_rate": None,
        "literary_quality": "not_measured",
        "input_sizes_by_role": sizes_by_role,
    }


def live_usage_summary(records: list[dict]) -> dict:
    durations = sorted(row["duration_ms"] for row in records if row.get("duration_ms") is not None)
    known = sum(row["cost_known"] for row in records)
    cost = sum(row["cost_usd"] or 0 for row in records)
    return {
        "paid_requests": len(records),
        "failed_requests": sum(row["failed"] for row in records),
        "known_cost_usd": cost,
        "cost_usd": cost if known == len(records) else None,
        "cost_coverage": {"known": known, "total": len(records)},
        "tokens_in": sum(row["tokens_in"] or 0 for row in records),
        "tokens_out": sum(row["tokens_out"] or 0 for row in records),
        "tokens_cached": sum(row["tokens_cached"] or 0 for row in records),
        "cache_coverage": {"known": sum(row["tokens_cached"] is not None for row in records), "total": len(records)},
        "request_latency_ms": {
            "samples": len(durations),
            "p50": durations[math.ceil(len(durations) * 0.5) - 1] if durations else None,
            "p95": durations[math.ceil(len(durations) * 0.95) - 1] if durations else None,
        },
        "literary_quality": "manual_review_required",
    }


async def _snapshot(url: str) -> dict:
    """Compare persisted mechanics without exporting names, text, secrets or IDs."""
    from sqlalchemy import select

    from app.db.models import Character, Entity, Event, InventoryItem, LlmCall, MasterTurn, Message
    from app.db.session import make_engine, make_sessionmaker

    engine = make_engine(url)
    try:
        async with make_sessionmaker(engine)() as s:
            events = (await s.scalars(select(Event))).all()
            characters = (await s.scalars(select(Character))).all()
            entities = (await s.scalars(select(Entity))).all()
            inventory = (await s.scalars(select(InventoryItem))).all()
            messages = (await s.scalars(select(Message))).all()
            turns = (await s.scalars(select(MasterTurn))).all()
            calls = (await s.scalars(select(LlmCall))).all()
            progress = []
            for message in messages:
                for part, value in ((message.data or {}).get("resolution_progress") or {}).items():
                    progress.append((part, value.get("status")))
            # Random instance identifiers are intentionally excluded, including
            # resource links. The fixtures assert exact identities when relevant.
            resources = [ch.resources or {} for ch in sorted(characters, key=lambda ch: ch.name)]
            encoded = json.dumps(resources, sort_keys=True)
            encoded = normalize_identities(encoded)
            return {
                "events": dict(sorted(Counter(e.tool for e in events).items())),
                "resources": json.loads(encoded),
                "inventory": sorted((i.item_template_id, i.qty, i.equipped) for i in inventory),
                "entities": sorted(
                    ((e.kind, e.template_id or "", e.state.get("hp"), e.zone) for e in entities), key=str
                ),
                "action_parts": sorted(progress),
                "turn_statuses": sorted(t.status for t in turns),
                "_calls": dict(sorted(Counter(call.purpose for call in calls).items())),
                "_fallback": sum(bool((call.diagnostics or {}).get("fallback_reason")) for call in calls),
                "_unknown_usage": sum(not call.cost_known for call in calls),
            }
    finally:
        await engine.dispose()


def normalize_identities(encoded: str) -> str:
    """Remove fresh row IDs and UUIDs from an outcome serialization, never model inputs."""
    encoded = re.sub(r"\b[a-z]+_[a-f0-9]{12,}\b", "<instance>", encoded)
    return re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<uuid>", encoded)


@pytest.fixture(autouse=True)
def _efficiency_instrumentation(request, monkeypatch):
    """Loaded only in child pytest via -p; ordinary project pytest is unaffected."""
    variant = os.environ.get("TALEFORGE_EVAL_VARIANT")
    kind = os.environ.get("TALEFORGE_EVAL_EXPERIMENT", "product")
    selected = os.environ.get("TALEFORGE_EVAL_CONTEXT_VARIANT") if kind != "product" else variant
    if not os.environ.get("TALEFORGE_EVAL_RESULT"):
        yield
        return
    config = ExperimentConfig(kind, (selected,))
    context_variant = selected if kind == "context" else None
    from app.agents.master import optimization, review, turn
    from app.core.world_generation import policy

    if kind == "product":
        flags = dict.fromkeys(optimization.FLAGS, variant == "optimized")
        for module in (optimization, review, turn):
            monkeypatch.setattr(module, "optimization_flags", lambda settings: flags.copy())
    elif kind == "tools":
        original_flags = optimization.optimization_flags

        def tools_flags(settings):
            return {**original_flags(settings), "tool_profiles": selected == "profile"}

        for module in (optimization, review, turn):
            monkeypatch.setattr(module, "optimization_flags", tools_flags)
    monkeypatch.setattr(policy, "root_seed", lambda campaign_id, target_id, phase: 0)
    random.seed(0)
    row = {
        "nodeid": request.node.nodeid,
        "status": "failed",
        "model_calls": {},
        "fallback": 0,
        "unknown_usage": 0,
        "snapshot": None,
        "effective_config": effective_config(config, selected),
        "measured_inputs": [],
        "parse_inputs": [],
        "assembler_calls": 0,
    }
    _RESULTS[request.node.nodeid] = row
    if context_variant is not None:
        row["effective_context_variant"] = context_variant
        from app.agents.master import prompt_context

        original_assembler = prompt_context.build_prompt_bundle
        if context_variant in {"legacy", "v1"}:
            from app.agents.master import narration
            from tools.context_eval_variants import historical_assembler

            history = historical_assembler()
            monkeypatch.setattr(narration, "render", history.render)

        async def dispatched(ctx, cfg, *, role, inputs):
            bundle = await assemble_variant(
                context_variant, ctx, cfg, role=role, inputs=inputs, revised=original_assembler
            )
            row["assembler_calls"] += 1
            return bundle

        monkeypatch.setattr(prompt_context, "build_prompt_bundle", dispatched)
    ask = turn.TurnMixin._ask
    from app.agents.master import parsing
    from app.core.llm_diagnostics import message_sizes

    original_parse = parsing.ParsingMixin._parse_call

    async def measured_parse(self, *args, **kwargs):
        # The original parser builds and dispatches the request. A local receiver
        # records it without mutating the shared client or rebuilding its inputs.
        client = self.llm

        class ParserReceiver:
            async def complete(self, messages, **options):
                package = package_for_variant(selected, {"messages": messages, "tools": options.get("tools")})
                row["parse_inputs"].append(
                    {
                        "purpose": "parse",
                        "digest": package["digest"],
                        "message_sizes": message_sizes(messages, options.get("tools") or []),
                    }
                )
                return await client.complete(messages, **options)

        return await original_parse(SimpleNamespace(llm=ParserReceiver()), *args, **kwargs)

    monkeypatch.setattr(parsing.ParsingMixin, "_parse_call", measured_parse)

    async def measured(self, calls, cfg, cid, seat_id, turn_id, purpose, messages, tools, *args, **kwargs):
        package = package_for_variant(selected, {"messages": messages, "tools": tools})
        row["measured_inputs"].append(
            {
                "purpose": purpose,
                "digest": package["digest"],
                "message_count": len(package["messages"]),
                "tool_count": len(package["tools"]),
                "tool_names": [(tool.get("function") or {}).get("name") for tool in package["tools"]],
                "message_roles": [message["role"] for message in package["messages"]],
                "prompt_metadata": kwargs.get("prompt_metadata"),
                "message_sizes": message_sizes(messages, tools or []),
            }
        )
        row["model_calls"][purpose] = row["model_calls"].get(purpose, 0) + 1
        row["unknown_usage"] += 1  # scripted counts are not provider usage
        row["fallback"] += int(bool((kwargs.get("prompt_metadata") or {}).get("fallback_reason")))
        token = _PURPOSE.set(purpose)
        try:
            return await ask(self, calls, cfg, cid, seat_id, turn_id, purpose, messages, tools, *args, **kwargs)
        finally:
            _PURPOSE.reset(token)

    monkeypatch.setattr(turn.TurnMixin, "_ask", measured)
    url = request.getfixturevalue("settings").database_url if "settings" in request.fixturenames else None
    yield
    if url:
        snapshot = asyncio.run(_snapshot(url))
        row["model_calls"] = snapshot.pop("_calls")
        row["fallback"] = snapshot.pop("_fallback")
        row["unknown_usage"] = snapshot.pop("_unknown_usage")
        row["snapshot"] = snapshot
    if context_variant is not None:
        digests = [item["digest"] for item in row["measured_inputs"]]
        row["context_package_digest"] = hashlib.sha256(json.dumps(digests, sort_keys=True).encode("utf-8")).hexdigest()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    row = _RESULTS.get(item.nodeid)
    if row is not None:
        if report.failed:
            row["status"] = "failed"
            row["failure_phase"] = report.when
        elif report.skipped:
            row["status"] = "skipped"
        elif report.when == "call":
            row["status"] = "passed"


def pytest_sessionfinish(session, exitstatus):
    destination = os.environ.get("TALEFORGE_EVAL_RESULT")
    if destination:
        Path(destination).write_text(json.dumps(list(_RESULTS.values()), ensure_ascii=False), encoding="utf-8")


def run_scripted(
    cases: list[dict],
    *,
    execute=subprocess.run,
    live_options: dict | None = None,
    experiment: ExperimentConfig | None = None,
    context_cases: Path | None = None,
) -> dict:
    variants = {}
    all_usage = []
    if live_options:
        if experiment is not None and experiment.kind != "product":
            raise ValueError("live evaluator supports only the product experiment")
        if any(case["nodeid"] != "tests/test_turn_efficiency.py::test_paired_scripted_turn[attack]" for case in cases):
            raise ValueError("live currently supports only the isolated attack case")
    selected_variants = experiment.variants if experiment is not None else ("legacy", "optimized")
    with tempfile.TemporaryDirectory(prefix="taleforge-efficiency-") as folder:
        for variant in selected_variants:
            destination = Path(folder) / f"{variant}.json"
            environment = {
                **{key: value for key, value in os.environ.items() if not key.startswith("TALEFORGE_EVAL_")},
                "TALEFORGE_EVAL_RESULT": str(destination),
                "PYTHONHASHSEED": "0",
            }
            if experiment is None or experiment.kind == "product":
                environment["TALEFORGE_EVAL_VARIANT"] = variant
            else:
                environment["TALEFORGE_EVAL_EXPERIMENT"] = experiment.kind
                environment["TALEFORGE_EVAL_CONTEXT_VARIANT"] = variant
            if context_cases is not None:
                environment["TALEFORGE_EVAL_CONTEXT_CASES"] = str(context_cases.resolve())
            # Always isolate from any configured test/live PostgreSQL database.
            environment.pop("TEST_DATABASE_URL", None)
            if live_options:
                remaining = live_options["budget"] - sum(row["cost_usd"] or 0 for row in all_usage)
                if remaining < live_options["reserve"] or any(
                    not row["cost_known"] or (row["cost_usd"] or 0) > live_options["reserve"] for row in all_usage
                ):
                    variants[variant] = {
                        "exit_code": 2,
                        "status": "budget_not_admitted",
                        "cases": [],
                        "summary": summarize([]),
                        "usage": [],
                    }
                    continue
                journal = live_options["journal_dir"] / f"{variant}.json"
                if journal.exists():
                    raise ValueError("live usage journal already exists; use a new output path")
                environment.update(
                    {
                        "TALEFORGE_EVAL_LIVE": "1",
                        "TALEFORGE_EVAL_BUDGET": str(remaining),
                        "TALEFORGE_EVAL_RESERVE": str(live_options["reserve"]),
                        "TALEFORGE_EVAL_MODEL": live_options["model"],
                        "TALEFORGE_EVAL_RUN_LABEL": live_options["campaign"],
                        "TALEFORGE_EVAL_JOURNAL": str(journal),
                    }
                )
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "tools.eval_turn_efficiency",
                "-n",
                "0",
                "-q",
                "--tb=short",
                *dict.fromkeys(case["nodeid"] for case in cases),
            ]
            completed = execute(
                command, cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            actual = json.loads(destination.read_text(encoding="utf-8")) if destination.exists() else []
            indexed = {row["nodeid"]: row for row in actual}
            rows = []
            for case in cases:
                # An unparameterized fixture may deliberately cover several
                # parameter combinations; every collected subcase must pass.
                matching = [
                    row
                    for node, row in indexed.items()
                    if node == case["nodeid"] or node.startswith(case["nodeid"] + "[")
                ]
                if not matching:
                    rows.append(
                        {**case, "status": "failed", "model_calls": {}, "snapshot": None, "failure_phase": "collection"}
                    )
                else:
                    for row in matching:
                        rows.append({**case, **row})
            variants[variant] = {"exit_code": completed.returncode, "summary": summarize(rows), "cases": rows}
            if live_options:
                usage = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else []
                variants[variant]["usage"] = usage
                variants[variant]["summary"].update(live_usage_summary(usage))
                all_usage.extend(usage)
            if completed.returncode and not live_options:
                # No provider text or raw database data, only scoped pytest diagnostics.
                print(completed.stdout[-12000:], file=sys.stderr)
                print(completed.stderr[-2000:], file=sys.stderr)
    mismatches = []
    baseline = variants[selected_variants[0]]["cases"]
    left = {row["nodeid"]: row for row in baseline if "nodeid" in row}
    for name in selected_variants[1:]:
        for row in variants[name]["cases"]:
            previous = left.get(row.get("nodeid"))
            if previous and (
                row.get("snapshot") != previous.get("snapshot") or row.get("status") != previous.get("status")
            ):
                mismatches.append(row["id"])
    variant_errors = []
    if experiment is not None and experiment.kind in {"context", "tools"}:
        for variant, payload in variants.items():
            for row in payload["cases"]:
                if (
                    row.get("effective_config", {}).get("selected_variant") != variant
                    or (row.get("scope") == "full_turn" and not (row.get("measured_inputs") or row.get("parse_inputs")))
                    or (
                        experiment.kind == "context"
                        and any(
                            item["purpose"] in {"decide", "narrate", "voice_line", "review"}
                            for item in row.get("measured_inputs", [])
                        )
                        and not row.get("assembler_calls")
                    )
                ):
                    variant_errors.append(row.get("id", variant))
    return {
        "mode": "live" if live_options else "scripted",
        "seed": 0,
        "models": live_options["model"] if live_options else "deterministic scripted replies",
        "voice": "disabled",
        "live_performed": bool(all_usage),
        "experiment": experiment.kind if experiment is not None else "product",
        "variants": variants,
        "mechanical_mismatches": sorted(set(mismatches)),
        "variant_errors": sorted(set(variant_errors)),
        "context_quality_violations": [
            {
                "variant": variant,
                "id": row["id"],
                "status": row["context_quality_status"],
                "roles": row["context_quality"],
            }
            for variant, payload in variants.items()
            for row in payload["cases"]
            if row.get("context_quality_status") in {"baseline_violations", "violations"}
        ],
        "limits": [
            "Mechanics cases exercise real tools directly; only full_turn cases measure the master loop.",
            "Fixtures assert individual world, resource, progress and visibility invariants.",
            "Snapshots exclude random identities; fixture assertions retain identity checks.",
            "Historical recall/privacy rubric violations are reported as baseline_violations; "
            "they do not invalidate a mechanically passing baseline. Revised role assertions remain strict.",
            (
                "Live attack only: fixed parser, fixed dice, identical provider model and disabled voice; "
                "one turn per variant; request latency has too few samples for savings conclusions; "
                "no cold/warm cache or literary quality assessment."
                if live_options
                else "No actual cost, cache, provider tokens, live latency or literary quality is measured."
            ),
        ],
        **(
            {
                "campaign_label": live_options["campaign"],
                "budget_usd": live_options["budget"],
                "request_reservation_usd": live_options["reserve"],
                "known_cost_usd": sum(row["cost_usd"] or 0 for row in all_usage),
                "cost_coverage": {"known": sum(row["cost_known"] for row in all_usage), "total": len(all_usage)},
                "cache_coverage": {
                    "known": sum(row["tokens_cached"] is not None for row in all_usage),
                    "total": len(all_usage),
                },
                "budget_overrun": sum(row["cost_usd"] or 0 for row in all_usage) > live_options["budget"],
                "reservation_overrun": any((row["cost_usd"] or 0) > live_options["reserve"] for row in all_usage),
                "literary_quality": "manual_review_required",
            }
            if live_options
            else {}
        ),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("scripted", "live"), required=True)
    parser.add_argument("--cases", type=Path, default=ROOT / "tests/fixtures/turn_efficiency.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--campaign")
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--max-request-cost-usd", type=float, help="Conservative reservation per paid request")
    parser.add_argument("--model", help="Same provider/model for both live variants")
    parser.add_argument("--isolated-test-campaign", action="store_true")
    parser.add_argument("--experiment", choices=("context", "tools", "product"), default="product")
    parser.add_argument("--context-variant", choices=("legacy", "v1", "revised", "all"))
    args = parser.parse_args(argv)
    args.context_variant = args.context_variant or ("legacy" if args.experiment == "product" else "revised")
    context_options = validate_context_options(args.experiment, args.context_variant)
    try:
        if args.mode == "live":
            validate_live(args.campaign, args.max_cost_usd, isolated=args.isolated_test_campaign)
            if (
                not args.model
                or not args.max_request_cost_usd
                or not math.isfinite(args.max_request_cost_usd)
                or not (0 < args.max_request_cost_usd <= args.max_cost_usd)
            ):
                raise ValueError("live requires --model and a positive --max-request-cost-usd within the budget")
            selected = [case for case in load_cases(args.cases) if case["id"] == "attack"]
            if len(selected) != 1:
                raise ValueError("live requires exactly one supported attack case")
            journal_dir = args.output.resolve().with_suffix(".usage")
            if journal_dir.exists():
                raise ValueError("live output usage directory exists; choose a new output path")
            journal_dir.mkdir(parents=True)
            report = run_scripted(
                selected,
                live_options={
                    "budget": args.max_cost_usd,
                    "reserve": args.max_request_cost_usd,
                    "model": args.model,
                    "campaign": args.campaign,
                    "journal_dir": journal_dir,
                },
            )
        else:
            if args.experiment == "context":
                document = json.loads(args.cases.read_text(encoding="utf-8"))
                scenarios = validate_context_cases(document)
                selected = [
                    {
                        "id": scenario["id"],
                        "nodeid": (
                            "tests/test_context_eval_scenarios.py::"
                            "test_context_evaluator_scenario[" + scenario["id"] + "]"
                        ),
                        "tags": scenario["rubric"],
                        "scope": "full_turn",
                    }
                    for scenario in scenarios
                ]
                config = ExperimentConfig(
                    kind="context",
                    variants=("legacy", "v1", "revised") if args.context_variant == "all" else (args.context_variant,),
                )
                report = run_scripted(selected, experiment=config, context_cases=args.cases)
            elif args.experiment == "tools":
                report = run_scripted(
                    load_cases(args.cases), experiment=ExperimentConfig(kind="tools", variants=("full", "profile"))
                )
            else:
                report = run_scripted(load_cases(args.cases))
        report["experiment"] = context_options["experiment"]
        report["context_variant"] = context_options["context_variant"]
        code = int(
            bool(report["mechanical_mismatches"])
            or report.get("budget_overrun", False)
            or report.get("reservation_overrun", False)
            or bool(report.get("variant_errors"))
            or any(variant["exit_code"] or variant["summary"]["failed"] for variant in report["variants"].values())
        )
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['mode']}: live_performed={report['live_performed']}; report={args.output}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
