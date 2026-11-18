import asyncio
import json
from types import SimpleNamespace

from app.agents.master.exploration import (
    MAX_DECIDE_CALLS,
    may_retry,
    obtain_exploration_action,
)
from app.db.models import Campaign, MasterTurn
from tests.test_exploration_master import proposal
from tests.test_prompting_slicers import context
from tests.test_universal_master import prepare
from tests.test_universal_resolution import setup

WAIT = {"source": "mundane", "player_request": "ordinary", "resolution": "automatic", "effects": [{"kind": "wait"}]}
LORE = {"need_lore": ["laws:1"]}
INVALID = "not json"
MISMATCH = {"verdict": "mismatch", "message": "Нужна форма, а не искры.", "covered_requirements": []}
SCOPE = {"user_id": "u", "seat_id": "seat", "actor_id": "hero", "allowed_target_ids": frozenset({"hero"})}


def text(reply):
    return reply if isinstance(reply, (str, Exception)) else json.dumps(reply)


async def drive(tmp_path, decides, reviews=(), trace=None, admission=None):
    """One pass of obtain_exploration_action over scripted replies; returns (result, trace, decide_calls)."""
    engine, maker = await setup(tmp_path)
    try:
        await prepare(maker)
        async with maker() as session:
            session.add(MasterTurn(id="t", campaign_id="c", status="running", trace={}))
            await session.commit()
            campaign = await session.get(Campaign, "c")
        script = {"exploration_decide": [text(r) for r in decides], "intent_review": [text(r) for r in reviews]}
        calls = []

        async def ask(purpose, messages):
            calls.append(purpose)
            reply = script[purpose].pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        trace = {} if trace is None else trace
        result = None
        try:
            result = await obtain_exploration_action(
                SimpleNamespace(maker=maker), campaign, "t", "m", trace, context(), SCOPE, ask
            )
        except Exception as exc:  # noqa: BLE001 — a crashed call is part of the scenario
            result = exc
        return result, trace, calls.count("exploration_decide")
    finally:
        await engine.dispose()


def run(tmp_path, *args, **kwargs):
    return asyncio.run(drive(tmp_path, *args, **kwargs))


def test_a_lore_fetch_does_not_eat_the_format_repair(tmp_path):
    result, trace, decides = run(tmp_path, [LORE, INVALID, WAIT])
    assert result.proposal is not None and decides == 3
    assert trace["proposal_budgets"]["m"]["lore"] == 1 and trace["proposal_budgets"]["m"]["format"] == 1


def test_a_meaning_disagreement_still_leaves_a_format_repair(tmp_path):
    result, trace, decides = run(tmp_path, [proposal(), INVALID, WAIT], reviews=[MISMATCH])
    assert result.proposal is not None and decides == 3
    assert trace["proposal_budgets"]["m"]["meaning"] == 1 and trace["proposal_budgets"]["m"]["format"] == 1


def test_format_failures_get_two_repairs_then_the_floor(tmp_path):
    result, trace, decides = run(tmp_path, [INVALID, INVALID, INVALID])
    assert decides == 3 and trace["proposal_budgets"]["m"]["format"] == 2
    assert result.proposal is not None  # the plain floor turn, not a refusal


def test_the_total_cap_is_four_decide_calls(tmp_path):
    result, trace, decides = run(tmp_path, [LORE, proposal(), INVALID, INVALID], reviews=[MISMATCH])
    assert decides == MAX_DECIDE_CALLS == 4 and trace["proposal_attempts"]["m"] == 4
    assert result.proposal is None and result.failure.code == "not_realised"  # magic never shaped does not happen


def test_recovery_after_a_crash_never_exceeds_the_cap(tmp_path):
    decides = [LORE, proposal(), INVALID, RuntimeError("offline")]
    first, trace, count = run(tmp_path, decides, reviews=[MISMATCH])
    assert isinstance(first, Exception) and count == 4
    stored = json.loads(json.dumps(trace))  # what a restarted turn reads back
    (tmp_path / "restart").mkdir()
    again, stored, count = run(tmp_path / "restart", [], trace=stored)
    assert count == 0 and not isinstance(again, Exception) and stored["proposal_attempts"]["m"] == 4


def test_a_legacy_trace_with_two_attempts_gets_no_new_call(tmp_path):
    legacy = {"proposal_attempts": {"m": 2}, "admissions": {"m": {"invalid_json": True}}}
    result, trace, decides = run(tmp_path, [], trace=legacy)
    assert decides == 0 and result.proposal is not None


def test_may_retry_reads_the_spent_allowance():
    trace = {"proposal_attempts": {"m": 2}, "proposal_budgets": {"m": {"lore": 1, "format": 1}}}
    assert may_retry(trace, "m", "format") and may_retry(trace, "m", "meaning") and not may_retry(trace, "m", "lore")
