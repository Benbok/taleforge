"""Boundary derivation and durable director work triggers (spec §15, §16, Task 15 / Gate B)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.narrative.contracts import (
    BoundaryRecord,
    EvidenceRecord,
    EvidenceRef,
    NarrativePolicy,
    TurnBoundaryState,
)
from app.db.models import NarrativeState, NarrativeWork, new_id
from app.db.narrative import ensure_state
from app.tools.registry import ToolContext

ADAPTATION_RESULTS = frozenset(
    {
        "adapt_story",
        "apply_narrative_fact",
        "apply_narrative_thread",
        "apply_existing_front_intent",
        "narrative_commitment",
    }
)

BOUNDARY_KINDS = frozenset(
    {
        "choice",
        "relationship",
        "situation_closed",
        "act_closed",
        "session_closed",
        "opportunities_exhausted",
        "front_threshold",
    }
)


def _is_adaptation_evidence(ev: EvidenceRecord) -> bool:
    """Check if evidence was produced by narrative adaptation itself."""
    if ev.applied_result in ADAPTATION_RESULTS:
        return True
    if ev.ref.kind == "narrative":
        return True
    if ev.ref.source_id.startswith("adapt_") or ev.ref.source_id.startswith("prop_"):
        return True
    return False


def derive_boundaries(
    events: tuple[EvidenceRecord, ...],
    turn: TurnBoundaryState,
    policy: NarrativePolicy,
) -> tuple[BoundaryRecord, ...]:
    """Derive deterministic narrative boundaries from committed evidence and turn context.

    Ensures no recursion from adaptation events, deduplicates identical boundaries,
    and merges supporting evidence into a single record per unique source key.
    """
    clean_events = [ev for ev in events if not _is_adaptation_evidence(ev)]

    candidates: list[BoundaryRecord] = []
    session_budget = turn.session_id or f"sess_{turn.id}"

    # 1. Event-based derivation
    for ev in clean_events:
        camp_id = ev.ref.campaign_id or "default"
        res = ev.applied_result or ""
        subj_key = ":".join(sorted(ev.subject_refs)) if ev.subject_refs else ev.ref.source_id

        if res in ("end_act", "act_closed"):
            candidates.append(
                BoundaryRecord(
                    campaign_id=camp_id,
                    kind="act_closed",
                    source_id=subj_key if ev.subject_refs else "act",
                    scope="future",
                    evidence_refs=(ev.ref,),
                    audience=turn.audience or (),
                    focus=turn.focus,
                    session_budget_ref=session_budget,
                    policy_version=policy.version,
                )
            )
        elif res in ("end_session", "session_closed"):
            candidates.append(
                BoundaryRecord(
                    campaign_id=camp_id,
                    kind="session_closed",
                    source_id=f"session_{turn.session_id or turn.id}",
                    scope="future",
                    evidence_refs=(ev.ref,),
                    audience=turn.audience or (),
                    focus=turn.focus,
                    session_budget_ref=session_budget,
                    policy_version=policy.version,
                )
            )
        elif res in ("advance_plot", "node_closed", "situation_closed"):
            candidates.append(
                BoundaryRecord(
                    campaign_id=camp_id,
                    kind="situation_closed",
                    source_id=subj_key,
                    scope="future",
                    evidence_refs=(ev.ref,),
                    audience=turn.audience or (),
                    focus=turn.focus,
                    session_budget_ref=session_budget,
                    policy_version=policy.version,
                )
            )
        elif (
            res in (
                "alliance_formed",
                "relationship_changed",
                "actor_killed",
                "character_died",
                "standing_response",
                "settle_standing_response",
            )
            or ev.ref.kind == "standing_response"
        ):
            candidates.append(
                BoundaryRecord(
                    campaign_id=camp_id,
                    kind="relationship",
                    source_id=subj_key,
                    scope="future",
                    evidence_refs=(ev.ref,),
                    audience=turn.audience or (),
                    focus=turn.focus,
                    session_budget_ref=session_budget,
                    policy_version=policy.version,
                )
            )
        elif res in ("front_threshold", "threat_step", "advance_front"):
            candidates.append(
                BoundaryRecord(
                    campaign_id=camp_id,
                    kind="front_threshold",
                    source_id=subj_key,
                    scope="future",
                    evidence_refs=(ev.ref,),
                    audience=turn.audience or (),
                    focus=turn.focus,
                    session_budget_ref=session_budget,
                    policy_version=policy.version,
                )
            )
        elif res in ("opportunities_exhausted",):
            candidates.append(
                BoundaryRecord(
                    campaign_id=camp_id,
                    kind="opportunities_exhausted",
                    source_id=subj_key,
                    scope="future",
                    evidence_refs=(ev.ref,),
                    audience=turn.audience or (),
                    focus=turn.focus,
                    session_budget_ref=session_budget,
                    policy_version=policy.version,
                )
            )
        elif (
            ev.status == "rejected"
            or res in ("transition_thread", "thread_transition", "choice_made", "player_choice")
        ):
            candidates.append(
                BoundaryRecord(
                    campaign_id=camp_id,
                    kind="choice",
                    source_id=subj_key,
                    scope="future",
                    evidence_refs=(ev.ref,),
                    audience=turn.audience or (),
                    focus=turn.focus,
                    session_budget_ref=session_budget,
                    policy_version=policy.version,
                )
            )

    # 2. Context / external boundary fallback
    if turn.external_boundary:
        camp_id = clean_events[0].ref.campaign_id if clean_events else "camp-1"
        if turn.phase in BOUNDARY_KINDS:
            kind = turn.phase
        else:
            kind = "choice"

        source_id = f"{kind}_{turn.id}"
        evidence_refs = tuple(ev.ref for ev in clean_events)
        candidates.append(
            BoundaryRecord(
                campaign_id=camp_id,
                kind=kind,
                source_id=source_id,
                scope="future",
                evidence_refs=evidence_refs,
                audience=turn.audience or (),
                focus=turn.focus,
                session_budget_ref=session_budget,
                policy_version=policy.version,
            )
        )

    # 3. Deduplicate by source_key and merge evidence_refs
    seen: dict[str, BoundaryRecord] = {}
    for b in candidates:
        key = b.source_key
        if key in seen:
            prev = seen[key]
            existing_ref_ids = {r.source_id for r in prev.evidence_refs}
            merged_refs = list(prev.evidence_refs)
            for ref in b.evidence_refs:
                if ref.source_id not in existing_ref_ids:
                    merged_refs.append(ref)
                    existing_ref_ids.add(ref.source_id)
            seen[key] = prev.model_copy(update={"evidence_refs": tuple(merged_refs)})
        else:
            seen[key] = b

    return tuple(seen.values())


async def enqueue_boundaries(
    ctx: ToolContext,
    boundaries: tuple[BoundaryRecord, ...],
) -> tuple[str, ...]:
    """Enqueue narrative boundaries as durable work in the current database transaction.

    Coalesces with existing pending work in the same scope, preserving all evidence/grounds.
    Returns the tuple of enqueued job IDs.
    """
    if not boundaries:
        return ()

    # Respect replan setting
    replan = (ctx.campaign.settings or {}).get("replan")
    if replan is False:
        return ()

    state = await ensure_state(ctx.session, ctx.campaign.id)
    if state.mode != "adaptive":
        return ()

    work_ids: list[str] = []
    now_utc = datetime.now(UTC)

    for b in boundaries:
        # Check if identical work already exists by source_key
        stmt = select(NarrativeWork).where(
            NarrativeWork.campaign_id == b.campaign_id,
            NarrativeWork.source_key == b.source_key,
        )
        existing = (await ctx.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            work_ids.append(existing.id)
            continue

        # Check for existing unclaimed pending work to coalesce with
        pending_stmt = select(NarrativeWork).where(
            NarrativeWork.campaign_id == b.campaign_id,
            NarrativeWork.scope == b.scope,
            NarrativeWork.status == "pending",
        )
        pending_work = (await ctx.session.execute(pending_stmt)).scalar_one_or_none()

        new_evidence_refs = [ref.model_dump() for ref in b.evidence_refs]

        if pending_work is not None:
            # Coalesce: preserve grounds from pending work and boundary
            combined_refs = list(pending_work.evidence_refs or [])
            existing_src_ids = {r.get("source_id") for r in combined_refs if isinstance(r, dict)}
            for r in new_evidence_refs:
                if r.get("source_id") not in existing_src_ids:
                    combined_refs.append(r)
                    existing_src_ids.add(r.get("source_id"))

            new_work = NarrativeWork(
                campaign_id=b.campaign_id,
                source_key=b.source_key,
                scope=b.scope,
                kind=b.kind,
                source_id=b.source_id,
                audience=list(b.audience),
                focus=b.focus or pending_work.focus,
                session_budget_ref=pending_work.session_budget_ref or b.session_budget_ref,
                policy_version=b.policy_version,
                evidence_refs=combined_refs,
                base={},
                proposal_id=new_id("prop"),
                draft=None,
                status="pending",
                created_at=now_utc,
                updated_at=now_utc,
            )
            ctx.session.add(new_work)
            await ctx.session.flush()

            pending_work.status = "superseded"
            pending_work.draft = {"superseded_by": new_work.id}
            pending_work.updated_at = now_utc
            work_ids.append(new_work.id)
        else:
            new_work = NarrativeWork(
                campaign_id=b.campaign_id,
                source_key=b.source_key,
                scope=b.scope,
                kind=b.kind,
                source_id=b.source_id,
                audience=list(b.audience),
                focus=b.focus,
                session_budget_ref=b.session_budget_ref,
                policy_version=b.policy_version,
                evidence_refs=new_evidence_refs,
                base={},
                proposal_id=new_id("prop"),
                draft=None,
                status="pending",
                created_at=now_utc,
                updated_at=now_utc,
            )
            ctx.session.add(new_work)
            await ctx.session.flush()
            work_ids.append(new_work.id)

    return tuple(work_ids)
