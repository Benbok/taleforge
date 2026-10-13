"""CLI tool for evaluating narrative adaptation quality and structural safety.

Usage:
    python tools/eval_narrative.py --cases tests/fixtures/narrative_quality.json \
        --mode scripted --output eval_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.core.narrative.quality import load_quality_cases, score_structural_quality


def run_evaluation(cases_path: Path, mode: str) -> dict[str, Any]:
    cases = load_quality_cases(cases_path)
    results: list[dict[str, Any]] = []

    passed = 0
    failed = 0
    skipped = 0

    print(f"=== Narrative Adaptation Quality Eval ({mode}) ===")
    print(f"Loaded {len(cases)} cases from {cases_path}")

    for case in cases:
        # In scripted mode, benchmark reference_good and verify reference_bad triggers rubric
        if mode == "scripted":
            good_report = score_structural_quality(case, case.reference_good)
            bad_report = score_structural_quality(case, case.reference_bad)

            ok = good_report.structural_pass and bad_report.requires_human_review
            status_text = "PASS" if ok else "FAIL"
            if ok:
                passed += 1
            else:
                failed += 1

            print(f"[{status_text}] {case.id}: {case.title}")
            results.append(
                {
                    "case_id": case.id,
                    "title": case.title,
                    "passed": ok,
                    "good_report": good_report.model_dump(),
                    "bad_report": bad_report.model_dump(),
                }
            )
        else:
            # Live mode with model invocation (requires active model configuration)
            skipped += 1
            print(f"[SKIP-LIVE] {case.id}: Live mode requires explicitly permitted model config (not available in CI)")
            results.append({"case_id": case.id, "status": "skipped_no_model"})

    total = len(cases)
    print(f"\nSummary: {passed}/{total} passed, {failed} failed, {skipped} skipped")

    return {
        "mode": mode,
        "cases_total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate narrative adaptation quality")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("tests/fixtures/narrative_quality.json"),
        help="Path to quality evaluation cases JSON fixture",
    )
    parser.add_argument(
        "--mode",
        choices=["scripted", "live"],
        default="scripted",
        help="Evaluation mode: scripted (deterministic benchmark) or live (with LLM provider)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to output JSON evaluation report",
    )

    args = parser.parse_args()

    if not args.cases.exists():
        sys.exit(f"Error: Fixture file not found: {args.cases}")

    report = run_evaluation(args.cases, args.mode)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Report written to {args.output}")

    if args.mode == "scripted" and report["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
