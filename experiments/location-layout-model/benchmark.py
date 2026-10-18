"""Live acceptance benchmark; run from the repository root with PYTHONPATH=.

Each case uses the production parser, obligations, provider and two-call limit.
No campaign/database writes. API calls are billed by the configured provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from app.agents import layout_model
from app.agents.llm import LiteLLMClient, parser_model_for
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.layout.spatial import Holder, Mandate, default_spatial
from app.core.world_generation.contracts import Blocked
from app.core.world_generation.service import LLM_LIMIT
from tests.layout_plan_pilot import temple_mandate


def cases() -> dict[str, Mandate]:
    result = {
        "temple_holders": temple_mandate(),
        "temple_no_holders": temple_mandate(anchors=(), residents=()),
    }
    for kind, name in (("tavern", "Придорожная таверна"), ("cave", "Подземные гроты"), ("port", "Старая гавань")):
        result[kind] = Mandate(
            place=name,
            spatial=default_spatial(name, template_id=f"location.{kind}"),
            anchors=[Holder(key="clue_logbook", name="Записи путешественника")],
            residents=[Holder(key="npc:npc_keeper", name="Смотритель")],
        )
    return result


async def main(args: argparse.Namespace) -> None:
    llm = LiteLLMClient()
    model = args.model or parser_model_for()
    provider = DeterministicLayoutProvider()
    records: list[dict] = []

    def check(intent):
        provider.propose(intent, seed=args.seed, root_id="benchmark_root")

    selected = cases()
    if args.case:
        selected = {key: selected[key] for key in args.case}
    report = {"model": model, "seed": args.seed, "runs": args.runs, "records": records}
    for label, mandate in selected.items():
        for run in range(args.runs):
            msgs: list = []
            record = {"case": label, "run": run + 1, "accepted": False, "attempts": []}
            records.append(record)
            for call in range(LLM_LIMIT):
                try:
                    intent, attempt, why = await layout_model.ask(
                        llm, mandate, model=model, api_base=None, msgs=msgs, check=check
                    )
                except Blocked as error:
                    record["blocked"] = {"reason": error.reason, "detail": error.detail}
                    break
                record["attempts"].append(asdict(attempt))
                record["accepted"] = intent is not None
                status = "accepted" if intent is not None else why or attempt.error or "failed"
                print(f"{label} run={run + 1} call={call + 1}: {status} cost=${attempt.cost:.6f}", flush=True)
                if intent is not None:
                    record["intent"] = intent.model_dump(mode="json")
                if intent is not None or why is None:
                    break
            # Save after every case so a failed/interrupted run still has evidence.
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    accepted = sum(record["accepted"] for record in records)
    first = sum(record["accepted"] and len(record["attempts"]) == 1 for record in records)
    calls = sum(len(record["attempts"]) for record in records)
    cost = sum(attempt["cost"] for record in records for attempt in record["attempts"])
    report["summary"] = {"total": len(records), "accepted": accepted, "first_call": first, "calls": calls, "cost": cost}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--model")
    parser.add_argument("--case", action="append", choices=list(cases()))
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
