"""Test factories and deterministic fixtures for narrative adaptation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import TypeAdapter

from app.core.narrative.contracts import (
    AdaptationProposal,
    BoundaryRecord,
    EvidenceRecord,
    EvidenceRef,
    FactRef,
    FactState,
    Ground,
    NarrativePermissions,
    NarrativePolicy,
    NarrativeSnapshot,
    NarrativeSource,
    Operation,
    ReadRef,
    SnapshotRef,
    ThreadState,
    VersionSet,
)

_OP_ADAPTER = TypeAdapter(Operation)


def boundary(**overrides: Any) -> BoundaryRecord:
    """Factory for BoundaryRecord with default test values."""
    defaults: dict[str, Any] = {
        "campaign_id": "camp-1",
        "kind": "turn",
        "source_id": "turn-1",
        "scope": "future",
        "evidence_refs": (),
        "audience": ("party",),
        "focus": None,
        "session_budget_ref": "sess-1",
        "policy_version": 1,
    }
    defaults.update(overrides)
    return BoundaryRecord(**defaults)


def policy(**overrides: Any) -> NarrativePolicy:
    """Factory for NarrativePolicy with default test values."""
    return NarrativePolicy(**overrides)


def fact(**overrides: Any) -> FactState:
    """Factory for FactState with defaults."""
    ref_overrides = overrides.pop("ref", None)
    if ref_overrides is None:
        snap_ref = SnapshotRef(
            kind="event",
            source_id="evt-1",
            typed_address="campaign:npc-1:motivation",
        )
        fact_ref = FactRef(
            campaign_id="camp-1",
            namespace="campaign",
            subject_id="npc-1",
            key="motivation",
            version=1,
            snapshot_ref=snap_ref,
        )
    else:
        fact_ref = ref_overrides

    defaults: dict[str, Any] = {
        "ref": fact_ref,
        "kind": "intent",
        "temporal_semantics": "current_state",
        "freedom": "draft",
        "value": "Ищет союзников для обороны города",
        "audience": ("party",),
        "depends_on": (),
    }
    defaults.update(overrides)
    return FactState(**defaults)


def thread(**overrides: Any) -> ThreadState:
    """Factory for ThreadState with defaults."""
    defaults: dict[str, Any] = {
        "id": "thread-1",
        "version": 1,
        "status": "offered",
        "audience": ("party",),
        "subject_refs": ("npc-1",),
        "plan_refs": ("act_1_node_1",),
        "parent_id": None,
        "source_refs": ("evt-1",),
    }
    defaults.update(overrides)
    return ThreadState(**defaults)


def snapshot(**overrides: Any) -> NarrativeSnapshot:
    """Factory for NarrativeSnapshot with procedural future defaults."""
    source = overrides.pop(
        "source",
        NarrativeSource(
            campaign_id="camp-1",
            scope="future",
            source_kind="work",
            source_id="work-1",
            stable_part=0,
        ),
    )
    base = overrides.pop(
        "base",
        VersionSet(
            world_revision=1,
            plan_version=1,
            narrative_revision=1,
            policy_version=1,
            operation_schema_version=1,
        ),
    )
    evidence_status = overrides.pop("evidence_status", "applied")
    evidence = overrides.pop(
        "evidence",
        (
            EvidenceRecord(
                ref=EvidenceRef(campaign_id="camp-1", kind="event", source_id="evt-1"),
                status=evidence_status,
                subject_refs=("npc-1",),
                audience=("party",),
                game_time=1000,
                applied_result="divergence_noted",
            ),
        ),
    )
    facts = overrides.pop("facts", (fact(),))
    actors = overrides.pop("actors", ("npc-1",))
    threads = overrides.pop("threads", (thread(),))
    fronts = overrides.pop("fronts", ())
    read_set = overrides.pop(
        "read_set",
        (ReadRef(kind="entity", id="npc-1", version=1),),
    )
    permissions = overrides.pop(
        "permissions",
        NarrativePermissions(
            anchors=(),
            mutable_fact_addresses=("campaign:npc-1:motivation",),
            operation_kinds=(
                "add_campaign_fact",
                "develop_actor_role",
                "revise_future_situation",
                "change_front_intent",
                "upsert_thread",
                "transition_thread",
                "reveal_fact",
                "introduce_actor",
                "settle_standing_response",
                "revise_draft_fact",
            ),
            supplement_scopes=("future",),
        ),
    )
    budgets = overrides.pop(
        "budgets",
        {"novelty_scene": 3, "novelty_session": 12, "operations": 8},
    )
    content_chain = overrides.pop("content_chain", ("content-1",))
    feedback = overrides.pop("feedback", ())
    author_attempt = overrides.pop("author_attempt", 0)

    defaults: dict[str, Any] = {
        "source": source,
        "proposal_id": "prop-1",
        "base": base,
        "evidence": evidence,
        "facts": facts,
        "actors": actors,
        "fronts": fronts,
        "threads": threads,
        "read_set": read_set,
        "permissions": permissions,
        "budgets": budgets,
        "content_chain": content_chain,
        "feedback": feedback,
        "author_attempt": author_attempt,
    }
    defaults.update(overrides)
    return NarrativeSnapshot(**defaults)


def proposal(
    snap: NarrativeSnapshot | None = None,
    *,
    operations: tuple[Operation, ...] = (),
    grounds: tuple[Ground, ...] | None = None,
    **overrides: Any,
) -> AdaptationProposal:
    """Factory for AdaptationProposal."""
    if snap is None:
        snap = snapshot()

    ground_kind = overrides.pop("ground_kind", "divergence")
    if grounds is None:
        ev_refs = (snap.evidence[0].ref,) if snap.evidence else ()
        grounds = (
            Ground(
                kind=ground_kind,
                evidence_refs=ev_refs,
                subject_refs=("npc-1",),
                confidence="explicit",
            ),
        )

    defaults: dict[str, Any] = {
        "schema_version": 1,
        "proposal_id": snap.proposal_id,
        "source": snap.source,
        "base": snap.base,
        "grounds": grounds,
        "summary": "Развить мотив NPC после неожиданного поворота",
        "operations": operations,
        "read_set": snap.read_set,
    }
    defaults.update(overrides)
    return AdaptationProposal(**defaults)


def op(kind: str, **args: Any) -> Operation:
    """Factory for validated discriminated Operation."""
    payload = {"kind": kind, **args}
    return _OP_ADAPTER.validate_python(payload)


class FakeClock:
    """Controllable deterministic UTC clock for time-dependent job/lease tests."""

    def __init__(self, start: datetime | None = None) -> None:
        self._current = start or datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self._current

    def advance(self, seconds: int) -> None:
        self._current += timedelta(seconds=seconds)
