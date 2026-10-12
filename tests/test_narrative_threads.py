"""Tests for narrative thread lifecycle, attention budgets, and persistence."""

from __future__ import annotations

import asyncio
from typing import Literal

from app.core.narrative.contracts import (
    EvidenceRecord,
    EvidenceRef,
    Ground,
    ThreadState,
)
from app.core.narrative.threads import (
    attention_count,
    transition_thread,
)
from app.db.models import Campaign, NarrativeThread, User
from app.db.narrative import load_threads
from app.db.session import make_engine, make_sessionmaker
from tests.narrative_helpers import thread


def interest_ground() -> Ground:
    return Ground(
        kind="interest",
        evidence_refs=(
            EvidenceRef(
                campaign_id="camp-1",
                kind="event",
                source_id="obs-1",
            ),
        ),
        subject_refs=("hero-1",),
        confidence="explicit",
    )


def consequence_ground(
    *,
    kind: Literal["message", "event"] = "event",
    source_id: str = "evt-1",
) -> Ground:
    return Ground(
        kind="consequence",
        evidence_refs=(
            EvidenceRef(
                campaign_id="camp-1",
                kind=kind,
                source_id=source_id,
            ),
        ),
        subject_refs=("hero-1",),
        confidence="explicit",
    )


def evidence_record(
    source_id: str = "evt-1",
    *,
    status: Literal["applied", "stated", "question", "rejected", "observed", "elapsed"] = "applied",
    applied_result: str | None = "choice_accepted",
    utterance_text: str | None = None,
    audience: tuple[str, ...] = ("party",),
    kind: Literal["message", "event"] = "event",
) -> EvidenceRecord:
    return EvidenceRecord(
        ref=EvidenceRef(campaign_id="camp-1", kind=kind, source_id=source_id),
        status=status,
        subject_refs=("hero-1",),
        audience=audience,
        game_time=1000,
        applied_result=applied_result,
        utterance_text=utterance_text,
    )


def test_offered_does_not_become_active_without_player_choice():
    result = transition_thread(thread(status="offered"), "active", interest_ground())
    assert result.violation == "player_choice_required"
    assert result.new_state is None


def test_offered_does_not_become_active_on_request_utterance_without_applied_outcome():
    # Via message kind
    ground_msg = consequence_ground(kind="message", source_id="msg-req")
    result_msg = transition_thread(thread(status="offered"), "active", ground_msg)
    assert result_msg.violation == "player_choice_required"
    assert result_msg.new_state is None

    # Via evidence record with utterance but no applied result
    ground_evt = consequence_ground(source_id="evt-req")
    rec = evidence_record(
        "evt-req",
        applied_result=None,
        utterance_text="Can you help us investigate the ruins?",
    )
    result_rec = transition_thread(thread(status="offered"), "active", ground_evt, (rec,))
    assert result_rec.violation == "player_choice_required"
    assert result_rec.new_state is None


def test_offered_becomes_active_with_confirmed_player_choice():
    ground = consequence_ground(source_id="evt-accept")
    t = thread(status="offered", version=1)
    rec = evidence_record("evt-accept", applied_result="quest_accepted")
    result = transition_thread(t, "active", ground, (rec,))
    assert result.violation is None
    assert result.new_state is not None
    assert result.new_state.status == "active"
    assert result.new_state.version == 2
    assert "evt-accept" in result.new_state.source_refs


def test_active_to_resolved_requires_consequence():
    t = thread(status="active")
    bad = transition_thread(t, "resolved", interest_ground())
    assert bad.violation == "consequence_ground_required"

    good = transition_thread(t, "resolved", consequence_ground())
    assert good.violation is None
    assert good.new_state is not None
    assert good.new_state.status == "resolved"


def test_resolved_is_terminal_and_child_thread_created():
    resolved = thread(status="resolved", id="th-main")
    result = transition_thread(resolved, "active", consequence_ground())
    assert result.violation == "resolved_terminal"

    child = ThreadState(
        id="th-main-child",
        status="offered",
        parent_id=resolved.id,
        audience=resolved.audience,
        subject_refs=resolved.subject_refs,
    )
    assert child.parent_id == "th-main"
    assert child.status == "offered"


def test_all_spec_transitions():
    g = consequence_ground()

    # offered -> abandoned
    res = transition_thread(thread(status="offered"), "abandoned", g)
    assert res.violation is None and res.new_state.status == "abandoned"

    # active -> abandoned
    res = transition_thread(thread(status="active"), "abandoned", g)
    assert res.violation is None and res.new_state.status == "abandoned"

    # offered -> dormant
    res = transition_thread(thread(status="offered"), "dormant", g)
    assert res.violation is None and res.new_state.status == "dormant"

    # active -> dormant
    res = transition_thread(thread(status="active"), "dormant", g)
    assert res.violation is None and res.new_state.status == "dormant"

    # dormant -> offered
    res = transition_thread(thread(status="dormant"), "offered", g)
    assert res.violation is None and res.new_state.status == "offered"

    # abandoned -> offered
    res = transition_thread(thread(status="abandoned"), "offered", g)
    assert res.violation is None and res.new_state.status == "offered"

    # Invalid transitions
    assert transition_thread(thread(status="dormant"), "active", g).violation == "invalid_transition"
    assert transition_thread(thread(status="abandoned"), "active", g).violation == "invalid_transition"
    assert transition_thread(thread(status="offered"), "resolved", g).violation == "invalid_transition"
    assert transition_thread(thread(status="dormant"), "abandoned", g).violation == "invalid_transition"


def test_abandoned_to_offered_retains_prior_refusal_history():
    t = thread(status="abandoned", source_refs=("reject-evt-1",))
    g = consequence_ground(source_id="new-occasion-evt")
    res = transition_thread(t, "offered", g)
    assert res.violation is None
    assert res.new_state is not None
    assert res.new_state.status == "offered"
    assert "reject-evt-1" in res.new_state.source_refs
    assert "new-occasion-evt" in res.new_state.source_refs


def test_private_rejection_and_audience_mismatch():
    t_private = thread(status="offered", audience=("hero-1",))

    # Foreign player cannot transition private thread
    g_foreign = consequence_ground(source_id="evt-h2")
    rec_foreign = evidence_record("evt-h2", audience=("hero-2",))
    res = transition_thread(t_private, "abandoned", g_foreign, (rec_foreign,))
    assert res.violation == "audience_mismatch"

    # Authorized player can reject privately
    g_authorized = consequence_ground(source_id="evt-h1")
    rec_auth = evidence_record("evt-h1", audience=("hero-1",))
    res_auth = transition_thread(t_private, "abandoned", g_authorized, (rec_auth,))
    assert res_auth.violation is None
    assert res_auth.new_state.status == "abandoned"
    assert res_auth.new_state.audience == ("hero-1",)


def test_private_rejection_overlays_audience():
    t_public = thread(status="offered", audience=())
    g_private = consequence_ground(source_id="evt-h1")
    rec_private = evidence_record("evt-h1", audience=("hero-1",))
    res = transition_thread(t_public, "abandoned", g_private, (rec_private,))
    assert res.violation is None
    assert res.new_state.status == "abandoned"
    assert res.new_state.audience == ("hero-1",)


def test_attention_count_filtering():
    threads = (
        thread(id="t1", status="active", audience=()),
        thread(id="t2", status="active", audience=("party",)),
        thread(id="t3", status="offered", audience=("hero-1",)),
        thread(id="t4", status="active", audience=("hero-2",)),
        thread(id="t5", status="dormant", audience=("hero-1",)),
        thread(id="t6", status="resolved", audience=()),
        thread(id="t7", status="abandoned", audience=()),
        thread(id="t8", status="hidden", audience=()),
    )

    # hero-1 sees t1, t2 (public/party) and t3 (private to hero-1), total 3
    assert attention_count(threads, audience=("hero-1",)) == 3

    # hero-2 sees t1, t2 (public/party) and t4 (private to hero-2), total 3
    assert attention_count(threads, audience=("hero-2",)) == 3

    # general public/party sees only t1 and t2, total 2
    assert attention_count(threads, audience=()) == 2
    assert attention_count(threads, audience=("party",)) == 2


def test_db_load_threads_with_audience_and_status(tmp_path):
    db_path = tmp_path / "threads.db"
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = make_sessionmaker(engine)

    async def go():
        async with engine.begin() as conn:
            await conn.run_sync(Campaign.metadata.create_all)

        async with session_maker() as session:
            session.add(User(id="user-1", name="alice", password_hash="hash"))
            await session.flush()
            session.add(Campaign(id="camp-1", name="Test Camp", owner_id="user-1", ruleset_version="1.0.0"))
            session.add_all(
                [
                    NarrativeThread(
                        campaign_id="camp-1",
                        thread_id="th-public",
                        status="active",
                        audience=[],
                    ),
                    NarrativeThread(
                        campaign_id="camp-1",
                        thread_id="th-hero1",
                        status="offered",
                        audience=["hero-1"],
                    ),
                    NarrativeThread(
                        campaign_id="camp-1",
                        thread_id="th-hero2",
                        status="active",
                        audience=["hero-2"],
                    ),
                    NarrativeThread(
                        campaign_id="camp-1",
                        thread_id="th-dormant",
                        status="dormant",
                        audience=["hero-1"],
                    ),
                ]
            )
            await session.commit()

        async with session_maker() as session:
            # Load offered and active for hero-1
            loaded = await load_threads(
                session,
                "camp-1",
                statuses=("offered", "active"),
                audience=("hero-1",),
                limit=10,
            )
            ids = [t.id for t in loaded]
            assert "th-public" in ids
            assert "th-hero1" in ids
            assert "th-hero2" not in ids
            assert "th-dormant" not in ids

        await engine.dispose()

    asyncio.run(go())
