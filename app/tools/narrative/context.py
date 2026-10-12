"""Bounded narrative snapshot builder."""

from __future__ import annotations

import secrets

from sqlalchemy import select

from app.core.narrative.contracts import (
    EvidenceRecord,
    FrontRef,
    FrontView,
    NarrativePermissions,
    NarrativePolicy,
    NarrativeSnapshot,
    ReadRef,
    SnapshotRequest,
    ThreadState,
    VersionSet,
)
from app.db.models import Event, NarrativeThread
from app.db.narrative import ensure_state, load_subject_facts
from app.tools.registry import ToolContext


async def load_snapshot(
    ctx: ToolContext,
    request: SnapshotRequest,
    *,
    policy: NarrativePolicy,
) -> NarrativeSnapshot:
    """Build a verified bounded narrative snapshot from tool context."""
    cid = ctx.campaign.id
    proposal_id = f"prop_{secrets.token_hex(8)}"

    st = await ensure_state(ctx.session, cid)
    plot_data = ctx.world.plot or {}
    plan_ver = plot_data.get("version", 1) if isinstance(plot_data, dict) else 1

    base = VersionSet(
        world_revision=ctx.world.revision,
        plan_version=plan_ver,
        narrative_revision=st.revision,
        policy_version=policy.version,
        operation_schema_version=1,
    )

    # 1. Evidence
    evidence_records: list[EvidenceRecord] = []
    if request.evidence_refs:
        for ev_ref in request.evidence_refs:
            if ev_ref.kind == "event":
                stmt = select(Event).where(Event.campaign_id == cid, Event.id == ev_ref.source_id)
                res = await ctx.session.execute(stmt)
                ev_row = res.scalar_one_or_none()
                if ev_row:
                    evidence_records.append(
                        EvidenceRecord(
                            ref=ev_ref,
                            status="applied",
                            subject_refs=(ev_row.actor_id,) if ev_row.actor_id else (),
                            audience=("party",),
                            game_time=ev_row.game_time,
                            applied_result=ev_row.tool,
                        )
                    )
            else:
                evidence_records.append(
                    EvidenceRecord(
                        ref=ev_ref,
                        status="applied",
                        audience=("party",),
                    )
                )

    # 2. Facts
    subject_ids = set(request.mutable_subject_refs)
    for ent_id in ctx.world.entities:
        subject_ids.add(ent_id)
    for ch_id in ctx.world.characters:
        subject_ids.add(ch_id)

    facts = await load_subject_facts(ctx.session, cid, tuple(subject_ids), limit=policy.max_snapshot_records)

    # 3. Actors
    actors = tuple(sorted(subject_ids))

    # 4. Fronts
    fronts_list: list[FrontView] = []
    antagonists = plot_data.get("antagonists", []) if isinstance(plot_data, dict) else []
    for ant in antagonists:
        if isinstance(ant, dict) and "id" in ant:
            f_ref = FrontRef(campaign_id=cid, source_kind="antagonist", source_id=ant["id"])
            fronts_list.append(
                FrontView(
                    ref=f_ref,
                    owner_ref=ant["id"],
                    goal=ant.get("goal") or ant.get("name") or "",
                    status="stopped" if ant.get("stopped") else "active",
                )
            )

    # 5. Threads
    stmt = (
        select(NarrativeThread)
        .where(NarrativeThread.campaign_id == cid)
        .order_by(NarrativeThread.last_developed_at.desc())
        .limit(policy.max_snapshot_threads)
    )
    th_res = await ctx.session.execute(stmt)
    th_rows = th_res.scalars().all()
    threads_list = tuple(
        ThreadState(
            id=r.thread_id,
            version=r.version,
            status=r.status,  # type: ignore[arg-type]
            audience=tuple(r.audience or ()),
            subject_refs=tuple(r.subject_refs or ()),
            plan_refs=tuple(r.plan_refs or ()),
            parent_id=r.parent_id,
            source_refs=tuple(r.source_refs or ()),
        )
        for r in th_rows
    )

    # 6. ReadSet
    read_set: list[ReadRef] = []
    for a in actors:
        read_set.append(ReadRef(kind="entity", id=a))
    for f in facts:
        read_set.append(
            ReadRef(kind="fact", id=f"{f.ref.namespace}:{f.ref.subject_id}:{f.ref.key}", version=f.ref.version)
        )
    for fr in fronts_list:
        read_set.append(ReadRef(kind="front", id=fr.ref.source_id))
    for th in threads_list:
        read_set.append(ReadRef(kind="thread", id=th.id, version=th.version))

    # 7. Budgets
    budgets = {
        "novelty_scene": policy.max_novelty_scene,
        "novelty_session": policy.max_novelty_session,
        "operations": policy.max_operations,
    }

    permissions = NarrativePermissions(
        anchors=(),
        mutable_fact_addresses=tuple(f"{f.ref.namespace}:{f.ref.subject_id}:{f.ref.key}" for f in facts),
        operation_kinds=policy.allowed_operation_kinds,
        supplement_scopes=policy.allowed_scopes,
    )

    content_chain = ()
    if hasattr(ctx.world.catalog, "chain"):
        content_chain = tuple(ctx.world.catalog.chain)

    return NarrativeSnapshot(
        source=request.source,
        proposal_id=proposal_id,
        base=base,
        evidence=tuple(evidence_records),
        facts=facts,
        actors=actors,
        fronts=tuple(fronts_list),
        threads=threads_list,
        read_set=tuple(read_set),
        permissions=permissions,
        budgets=budgets,
        content_chain=content_chain,
        feedback=request.feedback,
        author_attempt=0,
    )
