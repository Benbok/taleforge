"""Database persistence and adapters for narrative adaptation state and facts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.narrative.contracts import (
    FactRef,
    FactState,
    NarrativeSource,
    SnapshotRef,
    ThreadState,
)
from app.core.narrative.view import CampaignNarrativeView, compose_view
from app.db.models import Campaign, Event, NarrativeFact, NarrativeState, NarrativeThread


async def ensure_state(session: AsyncSession, campaign_id: str) -> NarrativeState:
    """Ensure a NarrativeState row exists for the given campaign."""
    res = await session.execute(select(NarrativeState).where(NarrativeState.campaign_id == campaign_id))
    state = res.scalar_one_or_none()
    if state is None:
        campaign = await session.get(Campaign, campaign_id)
        mode = "adaptive"
        if campaign and campaign.settings:
            mode = campaign.settings.get("narrative_mode") or campaign.settings.get("narrative", {}).get(
                "mode", "adaptive"
            )
        state = NarrativeState(
            campaign_id=campaign_id,
            revision=1,
            policy_version=1,
            mode=mode,
            recent_boundaries=[],
            budget_counters={},
        )
        session.add(state)
        await session.flush()
    return state


def _fact_state(row: NarrativeFact) -> FactState:
    """Строка narrative_facts как неизменяемый доменный FactState."""
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

    return FactState(
        ref=fact_ref,
        kind=row.kind,  # type: ignore[arg-type]
        temporal_semantics=row.temporal_semantics,  # type: ignore[arg-type]
        freedom=row.freedom,  # type: ignore[arg-type]
        value=row.value or "",
        audience=tuple(row.audience or ()),
        depends_on=tuple(deps),
    )


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
    return tuple(_fact_state(row) for row in res.scalars().all())


async def load_campaign_facts(
    session: AsyncSession,
    campaign_id: str,
    *,
    namespaces: tuple[str, ...] = ("module", "campaign"),
    limit: int = 200,
) -> tuple[FactState, ...]:
    """Переопределения кампании для единого представления: только своя кампания, ограниченный объём."""
    stmt = (
        select(NarrativeFact)
        .where(NarrativeFact.campaign_id == campaign_id, NarrativeFact.namespace.in_(namespaces))
        .order_by(NarrativeFact.created_at.asc(), NarrativeFact.id.asc())
        .limit(limit)
    )
    return tuple(_fact_state(row) for row in (await session.scalars(stmt)).all())


async def load_narrative_view(
    session: AsyncSession,
    campaign_id: str,
    plan: dict[str, Any],
    content_chain: tuple[Any, ...] = (),
) -> CampaignNarrativeView:
    """CampaignNarrativeView поверх общего каталога: каркас кампании и её разрешённые переопределения."""
    return compose_view(plan, await load_campaign_facts(session, campaign_id), content_chain)


async def sync_plan_metadata(session: AsyncSession, campaign: Any, plan: dict[str, Any]) -> None:
    """Метаданные закрепления каркаса для адаптивной кампании: при сохранении каркаса и включении режима."""
    state = await ensure_state(session, campaign.id)
    mode = (campaign.settings or {}).get("narrative_mode") or state.mode
    if mode == "adaptive" and plan:
        await initialize_plan_metadata(session, campaign.id, plan, mode=mode)


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


async def load_threads(
    session: AsyncSession,
    campaign_id: str,
    *,
    statuses: tuple[str, ...],
    audience: tuple[str, ...],
    limit: int = 20,
) -> tuple[ThreadState, ...]:
    """Load threads matching campaign, statuses, and audience filters."""
    from app.core.narrative.threads import is_thread_visible_to_audience

    stmt = select(NarrativeThread).where(NarrativeThread.campaign_id == campaign_id)
    if statuses:
        stmt = stmt.where(NarrativeThread.status.in_(statuses))
    stmt = stmt.order_by(NarrativeThread.last_developed_at.desc(), NarrativeThread.id.asc())

    res = await session.execute(stmt)
    rows = res.scalars().all()

    matched: list[ThreadState] = []
    for r in rows:
        aud = tuple(r.audience or ())
        if is_thread_visible_to_audience(aud, audience):
            matched.append(
                ThreadState(
                    id=r.thread_id,
                    version=r.version,
                    status=r.status,  # type: ignore[arg-type]
                    audience=aud,
                    subject_refs=tuple(r.subject_refs or ()),
                    plan_refs=tuple(r.plan_refs or ()),
                    parent_id=r.parent_id,
                    source_refs=tuple(r.source_refs or ()),
                )
            )
            if len(matched) >= limit:
                break

    return tuple(matched)


def narrative_key(source: NarrativeSource) -> str:
    """Stable SHA-256 idempotency key for narrative adaptations."""
    import hashlib

    return hashlib.sha256(source.source_key().encode("utf-8")).hexdigest()


async def find_receipt(session: AsyncSession, source: NarrativeSource) -> Event | None:
    """Find existing durable receipt event for a narrative source."""
    key = narrative_key(source)
    stmt = select(Event).where(
        Event.campaign_id == source.campaign_id,
        Event.idempotency_key == key,
        Event.tool == "adapt_story",
    )
    return await session.scalar(stmt)
