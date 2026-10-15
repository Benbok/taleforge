"""Read-only metadata report, compatible with the schema before the coverage migration.

python -m tools.llm_session_report --campaign ID --output report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import MetaData, Table, select, text

from app.config import Settings
from app.core.spend import session_report
from app.db.models import now
from app.db.session import make_engine


async def campaign_report(database_url: str, campaign_id: str) -> dict:
    engine = make_engine(database_url)
    try:
        async with engine.connect() as conn:
            if conn.dialect.name == "postgresql":
                await conn.execute(text("SET TRANSACTION READ ONLY"))
            else:
                await conn.execute(text("PRAGMA query_only=ON"))
            metadata = MetaData()

            # Reflection allows baseline collection before migrating the live game.
            def tables(sync):
                return tuple(Table(name, metadata, autoload_with=sync) for name in ("llm_calls", "master_turns"))

            calls_table, turns_table = await conn.run_sync(tables)
            # Explicit metadata whitelist: no prompt, error text, trace or messages are exported.
            call_fields = (
                "id",
                "campaign_id",
                "turn_id",
                "purpose",
                "model",
                "tokens_in",
                "tokens_out",
                "tokens_reasoning",
                "tokens_cached",
                "cost",
                "cost_known",
                "created_at",
            )
            columns = [calls_table.c[n] for n in call_fields if n in calls_table.c]
            rows = (
                (
                    await conn.execute(
                        select(*columns, calls_table.c.error.is_not(None).label("has_error")).where(
                            calls_table.c.campaign_id == campaign_id
                        )
                    )
                )
                .mappings()
                .all()
            )
            calls = [SimpleNamespace(**r, error=bool(r["has_error"])) for r in rows]
            turn_fields = ("id", "status", "started_at", "finished_at")
            rows = (
                (
                    await conn.execute(
                        select(*(turns_table.c[n] for n in turn_fields)).where(turns_table.c.campaign_id == campaign_id)
                    )
                )
                .mappings()
                .all()
            )
            turns = [SimpleNamespace(**r) for r in rows]
            result = session_report(calls, turns)
            result.update(
                campaign_id=campaign_id,
                generated_at=now().isoformat(),
                cutoff=max((c.created_at for c in calls), default=None),
            )
            result["cutoff"] = result["cutoff"].isoformat() if result["cutoff"] else None
            await conn.rollback()
            return result
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = asyncio.run(campaign_report(Settings.from_env().database_url, args.campaign))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Calls: {result['total']['calls']}; saved to {args.output}")


if __name__ == "__main__":
    main()
