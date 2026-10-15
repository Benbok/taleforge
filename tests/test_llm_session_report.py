from datetime import UTC, datetime, timedelta

from app.core.llm_diagnostics import prompt_sizes
from app.core.spend import session_report
from app.db.models import LlmCall, MasterTurn


def test_read_only_cli_handles_pre_migration_schema(tmp_path):
    import asyncio
    import sqlite3

    from tools.llm_session_report import campaign_report

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE llm_calls (id TEXT, campaign_id TEXT, turn_id TEXT, purpose TEXT, model TEXT,
                tokens_in INTEGER, tokens_out INTEGER, tokens_reasoning INTEGER, cost REAL,
                created_at DATETIME, error TEXT);
            CREATE TABLE master_turns (id TEXT, campaign_id TEXT, status TEXT,
                started_at DATETIME, finished_at DATETIME);
            INSERT INTO llm_calls VALUES ('call','c',NULL,'parse','m',100,40,25,.01,
                '2026-10-15 12:00:00','private error text');
        """)
    result = asyncio.run(campaign_report(f"sqlite+aiosqlite:///{path}", "c"))
    assert result["total"]["calls"] == 1
    assert result["total"]["cost_unknown_calls"] == 1
    assert result["total"]["errors"] == 1
    assert "private error text" not in str(result)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 1
        assert "cost_known" not in {r[1] for r in db.execute("PRAGMA table_info(llm_calls)")}


def test_session_report_counts_failed_rollback_and_unattributed_calls():
    start = datetime(2026, 10, 15, tzinfo=UTC)
    turns = [
        MasterTurn(
            id=f"t{i}",
            status="done" if i < 16 else "failed",
            started_at=start,
            finished_at=start + timedelta(seconds=i + 1),
        )
        for i in range(17)
    ]
    calls = [
        LlmCall(
            turn_id=f"t{i}",
            purpose="decide",
            model="m",
            tokens_in=100,
            tokens_cached=80,
            tokens_out=40,
            tokens_reasoning=25,
            cost=0.01,
            cost_known=True,
        )
        for i in range(17)
    ]
    calls += [
        LlmCall(
            turn_id="t16", purpose="decide", model="m", cost=0.02, cost_known=True, error="invalid output; rolled back"
        ),
        LlmCall(purpose="parse", model="m", cost=0, cost_known=False),
    ]
    report = session_report(calls, turns)
    assert (report["done_turns"], report["failed_turns"], report["unattributed_calls"]) == (16, 1, 1)
    assert report["mean_decide_done"] == 1
    assert report["mean_decide_all"] == 18 / 17
    assert report["total"]["cost"] == 0.19
    assert report["total"]["cost_unknown_calls"] == 1
    assert report["total"]["cache_unknown_calls"] == 2
    assert report["total"]["tokens_uncached_known"] == 340
    assert report["total"]["errors"] == 1
    assert report["duration_ms"]["done"]["p50"] == 8500
    assert report["by_purpose"]["parse"]["calls"] == 1


def test_historical_cost_is_unknown_even_when_nonzero():
    report = session_report([LlmCall(purpose="decide", cost=0.12)], [])
    assert report["total"]["cost"] == 0.12
    assert report["total"]["cost_known_calls"] == 0
    assert report["total"]["cost_unknown_calls"] == 1


def test_prompt_sizes_contains_only_sizes_and_estimate_method():
    sizes = prompt_sizes({"system": "секрет", "history": "hi"}, [{"function": {"name": "get_scene"}}])
    assert sizes["blocks"]["system"]["utf8_bytes"] == 12
    assert sizes["blocks"]["system"]["chars"] == 6
    assert sizes["estimate_method"] == "chars/4-ceil"
    assert "секрет" not in str(sizes) and "get_scene" not in str(sizes)
