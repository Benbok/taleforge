"""Domain logic for narrative fact sealing and dependency traversal."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.core.narrative.contracts import (
    FactRef,
    FactRevision,
    FactState,
    Ground,
)


class SealResult(BaseModel):
    """Result of sealing facts along their dependency graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    refs: tuple[FactRef, ...] = ()
    violations: tuple[str, ...] = ()


def _fact_key(ref: FactRef) -> tuple[str, str, str, str]:
    return (ref.campaign_id, ref.namespace, ref.subject_id, ref.key)


def seal_facts(
    facts: tuple[FactState, ...],
    used_refs: tuple[FactRef, ...],
    *,
    max_dependencies: int = 16,
    max_visited: int = 64,
) -> SealResult:
    """Traverse dependencies of used_refs and seal all transitively reached facts.

    Detects dependency cycles, limits traversal depth and dependency fan-out.
    Returns empty refs if any violation is encountered.
    """
    fact_map = {_fact_key(f.ref): f for f in facts}

    visited: set[tuple[str, str, str, str]] = set()
    result_refs: list[FactRef] = []

    root_cid = used_refs[0].campaign_id if used_refs else (facts[0].ref.campaign_id if facts else None)

    def dfs(curr_ref: FactRef, path: list[tuple[str, str, str, str]]) -> str | None:
        if root_cid is not None and curr_ref.campaign_id != root_cid:
            return "foreign_campaign"

        k = _fact_key(curr_ref)
        if k in path:
            return "dependency_cycle"
        if k in visited:
            return None

        if len(visited) >= max_visited:
            return "max_visited_exceeded"

        curr_fact = fact_map.get(k)
        if curr_fact is None:
            return "missing_dependency"

        if curr_fact.ref.version != curr_ref.version:
            return "stale_fact_version"

        if curr_fact.ref.campaign_id != curr_ref.campaign_id:
            return "foreign_campaign"

        if len(curr_fact.depends_on) > max_dependencies:
            return "max_dependencies_exceeded"

        visited.add(k)
        path.append(k)

        for dep_ref in curr_fact.depends_on:
            err = dfs(dep_ref, path)
            if err is not None:
                return err

        path.pop()
        result_refs.append(curr_ref)
        return None

    for root_ref in used_refs:
        err = dfs(root_ref, [])
        if err is not None:
            return SealResult(refs=(), violations=(err,))

    # Preserve deterministic order, deduplicating
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[FactRef] = []
    for r in result_refs:
        k = _fact_key(r)
        if k not in seen:
            seen.add(k)
            deduped.append(r)

    return SealResult(refs=tuple(deduped), violations=())


def revise_draft(
    current: FactState,
    new_value: str,
    ground: Ground,
    dependency_states: tuple[FactState, ...] = (),
) -> FactRevision:
    """Revise a draft narrative fact given grounds and dependencies."""
    violations: list[str] = []

    if current.freedom == "committed":
        violations.append("fact_committed")

    if current.temporal_semantics == "historical" and current.freedom == "committed":
        violations.append("historical_fact_immutable")

    if ground.kind not in ("divergence", "relationship", "consequence"):
        violations.append("invalid_ground_for_draft_revision")

    if violations:
        return FactRevision(before=current, after=None, violations=tuple(violations))

    new_ref = current.ref.model_copy(update={"version": current.ref.version + 1})
    after_state = current.model_copy(
        update={
            "ref": new_ref,
            "value": new_value,
        }
    )
    return FactRevision(before=current, after=after_state, violations=())
