"""Durable fact commitments and narration claim reservations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.narrative.contracts import (
    FactRef,
    FactState,
    SnapshotRef,
)
from app.core.narrative.facts import seal_facts
from app.db.models import NarrativeFact
from app.tools.registry import ToolContext


async def record_commitments(
    ctx: ToolContext,
    refs: tuple[FactRef | str | dict[str, Any], ...],
    *,
    reason: str,
    snapshot_ref: SnapshotRef,
) -> tuple[FactRef, ...]:
    """Transition draft facts and their transitive dependencies to committed status."""
    if not refs:
        return ()

    if snapshot_ref.kind not in ("package", "plan", "event"):
        raise ValueError(f"Invalid snapshot kind: {snapshot_ref.kind}")

    cid = ctx.campaign.id

    def _parse_raw_ref(r: FactRef | str | dict[str, Any]) -> tuple[str, str, str, str, int | None, SnapshotRef | None]:
        if isinstance(r, FactRef):
            if r.campaign_id != cid:
                raise ValueError("foreign_campaign")
            return (r.campaign_id, r.namespace, r.subject_id, r.key, r.version, r.snapshot_ref)
        elif isinstance(r, str):
            parts = r.split(":")
            if len(parts) == 3:
                return (cid, parts[0], parts[1], parts[2], None, None)
            elif len(parts) == 4:
                if parts[0] != cid:
                    raise ValueError("foreign_campaign")
                return (parts[0], parts[1], parts[2], parts[3], None, None)
            else:
                raise ValueError("invalid_fact_ref_format")
        elif isinstance(r, dict):
            ref_cid = r.get("campaign_id", cid)
            if ref_cid != cid:
                raise ValueError("foreign_campaign")
            snap = (
                SnapshotRef(**r["snapshot_ref"])
                if "snapshot_ref" in r and isinstance(r["snapshot_ref"], dict)
                else None
            )
            return (ref_cid, r["namespace"], r["subject_id"], r["key"], r.get("version"), snap)
        else:
            raise ValueError(f"Unsupported fact ref type: {type(r)}")

    # 1. Resolve and validate initial refs
    initial_refs: list[FactRef] = []
    loaded_rows: dict[tuple[str, str, str, str], NarrativeFact] = {}
    queue: list[tuple[str, str, str, str, int | None, SnapshotRef | None]] = []

    for r in refs:
        parsed = _parse_raw_ref(r)
        queue.append(parsed)

    visited_loading: set[tuple[str, str, str, str]] = set()

    # 2. Transitive loading of all dependencies
    while queue:
        ref_cid, ns, sub, key, expected_version, expected_snap = queue.pop(0)
        if ref_cid != cid:
            raise ValueError("foreign_campaign")

        k = (ref_cid, ns, sub, key)
        if k in visited_loading:
            if expected_version is not None and loaded_rows[k].version != expected_version:
                raise ValueError("stale_fact_version")
            continue

        visited_loading.add(k)
        if len(visited_loading) > 64:
            raise ValueError("max_visited_exceeded")

        row = loaded_rows.get(k)
        if row is None:
            stmt = select(NarrativeFact).where(
                NarrativeFact.campaign_id == ref_cid,
                NarrativeFact.namespace == ns,
                NarrativeFact.subject_id == sub,
                NarrativeFact.key == key,
            )
            res = await ctx.session.execute(stmt)
            row = res.scalar_one_or_none()
            if row is None:
                raise ValueError("missing_dependency")
            loaded_rows[k] = row

        if expected_version is not None and row.version != expected_version:
            raise ValueError("stale_fact_version")

        deps_list = row.depends_on or []
        if len(deps_list) > 16:
            raise ValueError("max_dependencies_exceeded")

        for dep in deps_list:
            dep_parsed = _parse_raw_ref(dep)
            queue.append(dep_parsed)

    # 3. Build initial FactRef list and FactState domain models
    def _row_to_fact_ref(row: NarrativeFact) -> FactRef:
        snap_d = row.snapshot_ref or {}
        s_ref = SnapshotRef(
            kind=snap_d.get("kind", "event"),
            source_id=snap_d.get("source_id", ""),
            version=snap_d.get("version"),
            typed_address=snap_d.get("typed_address", ""),
        )
        return FactRef(
            campaign_id=row.campaign_id,
            namespace=row.namespace,  # type: ignore[arg-type]
            subject_id=row.subject_id,
            key=row.key,  # type: ignore[arg-type]
            version=row.version,
            snapshot_ref=s_ref,
        )

    for r in refs:
        ref_cid, ns, sub, key, _, _ = _parse_raw_ref(r)
        row = loaded_rows[(ref_cid, ns, sub, key)]
        initial_refs.append(_row_to_fact_ref(row))

    fact_states: list[FactState] = []
    for row in loaded_rows.values():
        f_ref = _row_to_fact_ref(row)
        dep_refs: list[FactRef] = []
        for dep in row.depends_on or []:
            d_cid, d_ns, d_sub, d_key, _, _ = _parse_raw_ref(dep)
            d_row = loaded_rows.get((d_cid, d_ns, d_sub, d_key))
            if d_row is not None:
                dep_refs.append(_row_to_fact_ref(d_row))
            else:
                raise ValueError("missing_dependency")

        fact_states.append(
            FactState(
                ref=f_ref,
                kind=row.kind,  # type: ignore[arg-type]
                temporal_semantics=row.temporal_semantics,  # type: ignore[arg-type]
                freedom=row.freedom,  # type: ignore[arg-type]
                value=row.value or "",
                audience=tuple(row.audience or []),
                depends_on=tuple(dep_refs),
            )
        )

    # 4. Domain seal traversal
    seal_result = seal_facts(tuple(fact_states), tuple(initial_refs))
    if seal_result.violations:
        raise ValueError(f"Cannot record commitments: {', '.join(seal_result.violations)}")

    # 5. Apply commitments atomically to rows
    newly_sealed: list[FactRef] = []
    for ref in seal_result.refs:
        k = (ref.campaign_id, ref.namespace, ref.subject_id, ref.key)
        row = loaded_rows.get(k)
        if row is not None and row.freedom == "draft":
            row.freedom = "committed"
            row.snapshot_ref = snapshot_ref.model_dump()
            newly_sealed.append(ref)

    if newly_sealed:
        await ctx.session.flush()
        await ctx.record(
            "narrative_seal",
            hidden=True,
            payload={
                "reason": reason,
                "refs": [r.model_dump() for r in newly_sealed],
                "snapshot_ref": snapshot_ref.model_dump(),
            },
        )

    return tuple(newly_sealed)


async def reserve_narration_claims(
    maker: async_sessionmaker,
    campaign_id: str,
    turn_id: str,
    refs: tuple[FactRef, ...],
    audience: tuple[str, ...],
) -> tuple[FactRef, ...]:
    """Atomically commit and reserve fact claims prior to LLM narration composing."""
    if not refs:
        return ()

    reserved: list[FactRef] = []
    async with maker() as session:
        for ref in refs:
            stmt = select(NarrativeFact).where(
                NarrativeFact.campaign_id == campaign_id,
                NarrativeFact.namespace == ref.namespace,
                NarrativeFact.subject_id == ref.subject_id,
                NarrativeFact.key == ref.key,
            )
            res = await session.execute(stmt)
            row = res.scalar_one_or_none()
            if row is not None:
                row.freedom = "committed"
                aud_set = set(row.audience or [])
                aud_set.update(audience)
                row.audience = list(aud_set)
                reserved.append(ref)
        await session.commit()

    return tuple(reserved)
