"""Database persistence and adapters for narrative adaptation state and facts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.narrative.contracts import (
    FactRef,
    FactState,
    SnapshotRef,
)
from app.db.models import NarrativeFact, NarrativeState


async def ensure_state(session: AsyncSession, campaign_id: str) -> NarrativeState:
    """Ensure a NarrativeState row exists for the given campaign."""
    res = await session.execute(select(NarrativeState).where(NarrativeState.campaign_id == campaign_id))
    state = res.scalar_one_or_none()
    if state is None:
        state = NarrativeState(
            campaign_id=campaign_id,
            revision=1,
            policy_version=1,
            mode="strict",
            recent_boundaries=[],
            budget_counters={},
        )
        session.add(state)
        await session.flush()
    return state


async def load_subject_facts(
    session: AsyncSession,
    campaign_id: str,
    subject_ids: tuple[str, ...],
    *,
    limit: int = 80,
) -> tuple[FactState, ...]:
    """Load facts for given subject IDs as frozen domain FactState DTOs."""
    if not subject_ids:
        return ()

    stmt = (
        select(NarrativeFact)
        .where(
            NarrativeFact.campaign_id == campaign_id,
            NarrativeFact.subject_id.in_(subject_ids),
        )
        .order_by(NarrativeFact.created_at.asc(), NarrativeFact.id.asc())
        .limit(limit)
    )
    res = await session.execute(stmt)
    rows = res.scalars().all()

    facts: list[FactState] = []
    for row in rows:
        snap_dict = row.snapshot_ref or {}
        snap_ref = SnapshotRef(
            kind=snap_dict.get("kind", "event"),
            source_id=snap_dict.get("source_id", ""),
            version=snap_dict.get("version"),
            typed_address=snap_dict.get("typed_address", ""),
        )
        fact_ref = FactRef(
            campaign_id=row.campaign_id,
            namespace=row.namespace,  # type: ignore[arg-type]
            subject_id=row.subject_id,
            key=row.key,  # type: ignore[arg-type]
            version=row.version,
            snapshot_ref=snap_ref,
        )

        deps: list[FactRef] = []
        for d in row.depends_on or []:
            if isinstance(d, dict) and "snapshot_ref" in d:
                d_snap = SnapshotRef(**d["snapshot_ref"])
                deps.append(
                    FactRef(
                        campaign_id=d.get("campaign_id", row.campaign_id),
                        namespace=d.get("namespace", "campaign"),
                        subject_id=d.get("subject_id", ""),
                        key=d.get("key", "motivation"),
                        version=d.get("version", 1),
                        snapshot_ref=d_snap,
                    )
                )

        facts.append(
            FactState(
                ref=fact_ref,
                kind=row.kind,  # type: ignore[arg-type]
                temporal_semantics=row.temporal_semantics,  # type: ignore[arg-type]
                freedom=row.freedom,  # type: ignore[arg-type]
                value=row.value or "",
                audience=tuple(row.audience or ()),
                depends_on=tuple(deps),
            )
        )

    return tuple(facts)


async def initialize_plan_metadata(
    session: AsyncSession,
    campaign_id: str,
    plan: dict[str, Any],
    *,
    mode: str,
) -> None:
    """Initialize narrative metadata from a campaign plan dictionary."""
    state = await ensure_state(session, campaign_id)
    state.mode = mode

    plot = plan.get("plot") or {}
    secrets = plot.get("secrets") or plan.get("secrets") or []

    for sec in secrets:
        sec_id = sec.get("id")
        if not sec_id:
            continue

        stmt = select(NarrativeFact).where(
            NarrativeFact.campaign_id == campaign_id,
            NarrativeFact.namespace == "plan",
            NarrativeFact.subject_id == sec_id,
            NarrativeFact.key == "secret_truth",
        )
        res = await session.execute(stmt)
        existing = res.scalar_one_or_none()

        truth_val = sec.get("truth") or sec.get("title") or ""
        revealed = bool(sec.get("revealed", False))
        snap_ref = {
            "kind": "plan",
            "source_id": sec_id,
            "typed_address": f"plan:secret:{sec_id}",
        }

        if existing is None:
            new_fact = NarrativeFact(
                campaign_id=campaign_id,
                namespace="plan",
                subject_id=sec_id,
                key="secret_truth",
                version=1,
                kind="truth",
                temporal_semantics="historical",
                freedom="committed",
                value=truth_val,
                audience=["party"] if revealed else [],
                depends_on=[],
                source_refs=[],
                snapshot_ref=snap_ref,
            )
            session.add(new_fact)
        else:
            existing.value = truth_val
            existing.freedom = "committed"
            if revealed and "party" not in existing.audience:
                existing.audience = [*existing.audience, "party"]

    # Parse open nodes from acts
    acts = plan.get("acts") or []
    for act in acts:
        act_id = act.get("id", "act_1")
        nodes = act.get("nodes") or []
        for node in nodes:
            node_id = node.get("id")
            if not node_id:
                continue

            stmt = select(NarrativeFact).where(
                NarrativeFact.campaign_id == campaign_id,
                NarrativeFact.namespace == "plan",
                NarrativeFact.subject_id == node_id,
                NarrativeFact.key == "situation_premise",
            )
            res = await session.execute(stmt)
            existing = res.scalar_one_or_none()

            summary = node.get("summary") or ""
            snap_ref = {
                "kind": "plan",
                "source_id": node_id,
                "typed_address": f"plan:act:{act_id}:node:{node_id}",
            }

            if existing is None:
                new_fact = NarrativeFact(
                    campaign_id=campaign_id,
                    namespace="plan",
                    subject_id=node_id,
                    key="situation_premise",
                    version=1,
                    kind="intent",
                    temporal_semantics="current_state",
                    freedom="draft",
                    value=summary,
                    audience=["party"],
                    depends_on=[],
                    source_refs=[],
                    snapshot_ref=snap_ref,
                )
                session.add(new_fact)
            else:
                existing.value = summary

    await session.flush()
