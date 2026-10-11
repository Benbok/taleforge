"""Explicit hardware pilot; writes reusable audition files, never sends game events."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from pathlib import Path

from app.config import Settings
from app.sfx.contracts import SfxInput, parameters
from app.sfx.worker import Worker

PROMPTS = (
    "A heavy wooden door creaks slowly in an empty stone room",
    "A short distant thunder clap with rain falling onto stone",
    "Metal chains rattle and a heavy iron gate slams shut",
)


async def benchmark(output: Path, count: int, duration: float) -> dict:
    cfg = Settings.from_env()
    output.mkdir(parents=True, exist_ok=True)
    worker = Worker(None, cfg)
    rows = []
    for i in range(count):
        request = SfxInput(description=PROMPTS[i % len(PROMPTS)], duration_seconds=duration)
        spec = parameters(request, cfg)
        path = output / f"pilot-{i + 1}.ogg"
        started = time.monotonic()
        try:
            meta = await worker.render(spec, i, path)
            row = {"status": "ready", **meta}
        except Exception as exc:
            path.unlink(missing_ok=True)
            row = {"status": "failed", "error": (str(exc) or type(exc).__name__)[:500]}
        rows.append(
            {"description": request.description, "seed": i, "elapsed_seconds": time.monotonic() - started, **row}
        )
    timings = sorted(row["elapsed_seconds"] for row in rows if row["status"] == "ready")
    report = {
        "model": cfg.sfx_model,
        "device": cfg.sfx_device,
        "threads": cfg.sfx_threads,
        "timeout_seconds": cfg.sfx_timeout_seconds,
        "successful": len(timings),
        "total": count,
        "p50_seconds": timings[math.ceil(len(timings) * 0.5) - 1] if timings else None,
        "p95_seconds": timings[math.ceil(len(timings) * 0.95) - 1] if timings else None,
        "samples": rows,
    }
    try:
        import resource

        report["peak_child_rss_mib"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    except ImportError:
        pass
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("audio/sfx-pilot"))
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--duration", type=float, default=3)
    args = parser.parse_args()
    if not 1 <= args.count <= 20 or not 1 <= args.duration <= 4:
        parser.error("count must be 1–20; duration must be 1–4 seconds")
    result = asyncio.run(benchmark(args.output, args.count, args.duration))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["successful"] != result["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
