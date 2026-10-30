"""Opt-in paid evaluation: python -m tests.eval.run --n 5 [--save]."""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.agents.llm import LiteLLMClient, decide_model_for, repair_json, reply_audit_error
from app.agents.master.prompting.messages import cacheable, decide_messages, request_size
from app.agents.master.universal import STRUCTURED_MAX_TOKENS, provider_schema
from app.rules.universal.exploration import IntentV2
from tests.eval.capture import FIXTURES
from tests.eval.cases import CASES
from tests.eval.checks import check

BASELINE = Path(__file__).with_name("baseline.json")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def evaluate(args):
    cases = [case for case in CASES if not args.cases or case.name in args.cases.split(",")]
    if not cases or args.n < 1:
        raise ValueError("Select at least one case and a positive repeat count")
    if args.cases and set(args.cases.split(",")) - {case.name for case in cases}:
        raise ValueError("Unknown case name")
    target = Path(args.output) if args.output else BASELINE if args.save else None
    if target and target.exists():
        raise ValueError(f"Refusing to overwrite existing measurements: {target}")
    model = decide_model_for()
    schema = provider_schema(IntentV2)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "submit_action",
                "description": "Semantic intent for server validation",
                "parameters": schema,
            },
        }
    ]
    llm = LiteLLMClient()
    semaphore = asyncio.Semaphore(args.concurrency)
    rows = []
    fixtures = {
        name: json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        for name in {case.fixture for case in cases}
    }

    async def once(case, repeat):
        context = {**fixtures[case.fixture], "source": case.source}
        messages = decide_messages(context)
        row = {
            "case": case.name,
            "repeat": repeat,
            "size": request_size(messages, tools),
            "tokens_in": 0,
            "tokens_cached": None,
            "attempts": 1,
            "provider_error": False,
        }
        async with semaphore:
            try:
                reply = await llm.complete(
                    cacheable(messages, model),
                    model=model,
                    tools=tools,
                    tool_choice={"type": "function", "function": {"name": "submit_action"}},
                    max_tokens=STRUCTURED_MAX_TOKENS,
                    temperature=0.8,
                )
                row.update(
                    tokens_in=reply.tokens_in,
                    tokens_cached=reply.tokens_cached,
                    tokens_out=reply.tokens_out,
                    cost=reply.cost,
                    cost_known=reply.cost_known,
                    latency_ms=reply.latency_ms,
                )
                call = next((call for call in reply.tool_calls if call.name == "submit_action"), None)
                raw = call.arguments if call else repair_json(reply.text)
                row["intent"] = raw
                row["issues"] = [reply_audit_error(reply)] if reply_audit_error(reply) else check(case, raw)
            except Exception as exc:
                # No credentials or provider response bodies are persisted in the report.
                row.update(issues=[f"provider: {type(exc).__name__}"], provider_error=True)
        row["success"] = not row["issues"]
        rows.append(row)
        print(f"{case.name} {repeat + 1}/{args.n}: {'PASS' if row['success'] else row['issues']}", flush=True)

    await asyncio.gather(*(once(case, repeat) for case in cases for repeat in range(args.n)))
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "model": model,
        "n": args.n,
        "cases": [case.name for case in cases],
        "fixtures_hash": digest(fixtures),
        "schema_hash": digest(schema),
        "request_hashes": {
            case.name: digest(decide_messages({**fixtures[case.fixture], "source": case.source})) for case in cases
        },
        "success_rate": sum(row["success"] for row in rows) / len(rows),
        "provider_errors": sum(row["provider_error"] for row in rows),
        "mean_tokens_in": sum(row["tokens_in"] for row in rows) / len(rows),
        "total_cost": sum(row.get("cost", 0) for row in rows),
        "rows": sorted(rows, key=lambda row: (row["case"], row["repeat"])),
    }
    print("case | success | mean tokens in | mean cached | request parts")
    for case in cases:
        subset = [row for row in rows if row["case"] == case.name]
        cached = [row["tokens_cached"] for row in subset if row["tokens_cached"] is not None]
        print(
            f"{case.name} | {sum(row['success'] for row in subset)}/{args.n} | "
            f"{sum(row['tokens_in'] for row in subset) / args.n:.0f} | "
            f"{sum(cached) / len(cached) if cached else 'unknown'} | {len(subset[0]['size']) - 1}"
        )
    if BASELINE.exists() and not args.save:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        comparable = all(result[key] == baseline[key] for key in ("model", "cases", "fixtures_hash", "n"))
        result["gate_passed"] = (
            comparable and not result["provider_errors"] and (result["success_rate"] >= baseline["success_rate"] - 0.05)
        )
        print(
            f"baseline={baseline['success_rate']:.1%}, current={result['success_rate']:.1%}, "
            f"gate={result['gate_passed']}"
        )
    print(f"success={result['success_rate']:.1%}, cost=${result['total_cost']:.4f}")
    if target:
        # Failed API calls cannot establish a quality baseline.
        if args.save and result["provider_errors"]:
            raise RuntimeError("Baseline not saved: provider failures must be resolved first")
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result.get("gate_passed") is False or result["provider_errors"]:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=5)
    parser.add_argument("--cases")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=4)
    asyncio.run(evaluate(parser.parse_args()))


if __name__ == "__main__":
    main()
