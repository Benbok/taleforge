"""Durable narrative director work enqueueing and coalescing (Task 15 / Gate B)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.narrative.contracts import BoundaryRecord
from app.db.models import NarrativeWork, new_id
from app.db.narrative import ensure_state
from app.tools.registry import ToolContext


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
