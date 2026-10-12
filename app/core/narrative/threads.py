"""Narrative thread lifecycle transitions and audience attention tracking."""

from __future__ import annotations

from app.core.narrative.contracts import (
    EvidenceRecord,
    Ground,
    ThreadState,
    ThreadTransition,
)

_VALID_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("offered", "active"),
        ("offered", "abandoned"),
        ("active", "abandoned"),
        ("offered", "dormant"),
        ("active", "dormant"),
        ("active", "resolved"),
        ("dormant", "offered"),
        ("abandoned", "offered"),
    }
)


def is_thread_visible_to_audience(
    thread_audience: tuple[str, ...],
    viewer_audience: tuple[str, ...],
) -> bool:
    """Check if thread is accessible to the given viewer audience.

    - Thread with empty audience or 'party' is public to all viewers.
    - If viewer is public (empty or 'party'), only public threads are visible (avoids leaking private threads).
    - If both thread and viewer specify non-empty audiences, they must overlap.
    """
    if not thread_audience or "party" in thread_audience:
        return True
    if not viewer_audience or "party" in viewer_audience:
        return False
    return bool(set(thread_audience) & set(viewer_audience))


def attention_count(
    threads: tuple[ThreadState, ...],
    audience: tuple[str, ...],
) -> int:
    """Calculate active audience attention budget.

    Only counts offered and active threads visible to the given audience.
    Excludes dormant, resolved, abandoned, hidden, and foreign private threads.
    """
    count = 0
    for t in threads:
        if t.status in ("offered", "active") and is_thread_visible_to_audience(t.audience, audience):
            count += 1
    return count


def transition_thread(
    state: ThreadState,
    target: str,
    ground: Ground,
    evidence: tuple[EvidenceRecord, ...] = (),
) -> ThreadTransition:
    """Perform verified state transition on a narrative thread."""
    if state.status == target:
        return ThreadTransition(violation="already_in_target_status")

    if state.status == "resolved":
        return ThreadTransition(violation="resolved_terminal")

    if (state.status, target) not in _VALID_TRANSITIONS:
        return ThreadTransition(violation="invalid_transition")

    if not ground.evidence_refs:
        return ThreadTransition(
            violation="player_choice_required" if target == "active" else "source_not_applied"
        )

    evidence_map = {e.ref.source_id: e for e in evidence}

    # Target-specific ground validations
    if target == "active":
        if ground.kind != "consequence":
            return ThreadTransition(violation="player_choice_required")
        for ev_ref in ground.evidence_refs:
            if ev_ref.kind == "message":
                return ThreadTransition(violation="player_choice_required")
            rec = evidence_map.get(ev_ref.source_id)
            if rec is not None:
                if rec.status in ("question", "draft", "rejected"):
                    return ThreadTransition(violation="source_not_applied")
                if rec.utterance_text is not None and rec.applied_result is None:
                    return ThreadTransition(violation="player_choice_required")
                if rec.applied_result is None:
                    return ThreadTransition(violation="player_choice_required")

    elif target == "resolved":
        if ground.kind != "consequence":
            return ThreadTransition(violation="consequence_ground_required")
        for ev_ref in ground.evidence_refs:
            rec = evidence_map.get(ev_ref.source_id)
            if rec is not None:
                if rec.status in ("question", "draft", "rejected"):
                    return ThreadTransition(violation="source_not_applied")
                if rec.applied_result is None:
                    return ThreadTransition(violation="consequence_ground_required")

    else:
        for ev_ref in ground.evidence_refs:
            rec = evidence_map.get(ev_ref.source_id)
            if rec is not None and rec.status in ("question", "draft", "rejected"):
                return ThreadTransition(violation="source_not_applied")

    # Audience check: evidence must be authorized
    if state.audience and "party" not in state.audience:
        for ev_ref in ground.evidence_refs:
            rec = evidence_map.get(ev_ref.source_id)
            if rec is not None and rec.audience and "party" not in rec.audience:
                if not any(a in state.audience for a in rec.audience):
                    return ThreadTransition(violation="audience_mismatch")

    # Determine audience overlay
    new_audience = state.audience
    if target == "abandoned":
        for ev_ref in ground.evidence_refs:
            rec = evidence_map.get(ev_ref.source_id)
            if rec is not None and rec.audience and "party" not in rec.audience:
                if not state.audience or "party" in state.audience:
                    new_audience = rec.audience
                    break

    # Accumulate source_refs
    new_evidence_ids = tuple(ev_ref.source_id for ev_ref in ground.evidence_refs if ev_ref.source_id)
    new_source_refs = tuple(dict.fromkeys((*state.source_refs, *new_evidence_ids)))

    new_state = ThreadState(
        id=state.id,
        version=state.version + 1,
        status=target,  # type: ignore[arg-type]
        audience=new_audience,
        subject_refs=state.subject_refs,
        plan_refs=state.plan_refs,
        parent_id=state.parent_id,
        source_refs=new_source_refs,
    )
    return ThreadTransition(new_state=new_state, violation=None)
