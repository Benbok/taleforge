"""Pure domain admission and policy checks for narrative adaptations."""

from __future__ import annotations

from app.core.narrative.contracts import (
    AdaptationAdmission,
    AdaptationProposal,
    NarrativePolicy,
    NarrativeSnapshot,
    ReadRef,
    Violation,
)
from app.core.narrative.operations import (
    _OPERATION_SPECS,
    ACTIVE_OPERATION_KINDS,
    novelty_cost,
    operation_specs,
)

__all__ = [
    "admit_adaptation",
    "novelty_cost",
    "operation_specs",
]


def admit_adaptation(
    snapshot: NarrativeSnapshot,
    proposal: AdaptationProposal,
    policy: NarrativePolicy,
) -> AdaptationAdmission:
    """Validate an adaptation proposal against snapshot and policy invariants.

    Pure function: no DB, no LLM, no side-effects. Follows spec §10.1 order.
    """
    # 1. Contract and Identity
    if proposal.schema_version != 1:
        return AdaptationAdmission(
            status="denied",
            reason_code="unsupported_schema_version",
            violations=(Violation(code="unsupported_schema_version"),),
            read_set=snapshot.read_set,
        )

    if proposal.proposal_id != snapshot.proposal_id:
        return AdaptationAdmission(
            status="denied",
            reason_code="unknown_source",
            violations=(Violation(code="proposal_id_mismatch"),),
            read_set=snapshot.read_set,
        )

    if proposal.source != snapshot.source:
        return AdaptationAdmission(
            status="denied",
            reason_code="unknown_source",
            violations=(Violation(code="source_mismatch"),),
            read_set=snapshot.read_set,
        )

    if proposal.base.world_revision != snapshot.base.world_revision:
        return AdaptationAdmission(
            status="denied",
            reason_code="stale_read_set",
            violations=(Violation(code="world_revision_mismatch"),),
            read_set=snapshot.read_set,
        )

    if proposal.base.policy_version != policy.version:
        return AdaptationAdmission(
            status="denied",
            reason_code="policy_changed",
            violations=(Violation(code="policy_version_mismatch"),),
            read_set=snapshot.read_set,
        )

    if policy.mode == "strict":
        return AdaptationAdmission(
            status="denied",
            reason_code="policy_strict_mode",
            violations=(Violation(code="strict_mode_active"),),
            read_set=snapshot.read_set,
        )

    if proposal.source.scope not in policy.allowed_scopes:
        return AdaptationAdmission(
            status="denied",
            reason_code="scope_not_allowed",
            violations=(Violation(code="scope_not_allowed", target_ref=proposal.source.scope),),
            read_set=snapshot.read_set,
        )

    # Deferred checks: future scope while narration is pending, or active combat in scene
    if proposal.source.scope == "future" and snapshot.budgets.get("pending_narration", 0) > 0:
        return AdaptationAdmission(
            status="deferred",
            reason_code="narration_pending",
            violations=(),
            read_set=snapshot.read_set,
        )

    if proposal.source.scope == "scene" and snapshot.budgets.get("combat_active", 0) > 0:
        return AdaptationAdmission(
            status="deferred",
            reason_code="combat_scope_locked",
            violations=(),
            read_set=snapshot.read_set,
        )

    # 2. Grounds verification
    if len(proposal.grounds) == 0:
        return AdaptationAdmission(
            status="denied",
            reason_code="missing_ground",
            violations=(Violation(code="missing_ground"),),
            read_set=snapshot.read_set,
        )

    if len(proposal.grounds) > policy.max_grounds:
        return AdaptationAdmission(
            status="denied",
            reason_code="grounds_limit",
            violations=(Violation(code="grounds_limit"),),
            read_set=snapshot.read_set,
        )

    evidence_map = {ev.ref.source_id: ev for ev in snapshot.evidence}
    for ground in proposal.grounds:
        if len(ground.evidence_refs) == 0:
            return AdaptationAdmission(
                status="denied",
                reason_code="source_not_applied",
                violations=(Violation(code="missing_evidence_ref"),),
                read_set=snapshot.read_set,
            )

        for ev_ref in ground.evidence_refs:
            ev_rec = evidence_map.get(ev_ref.source_id)
            if ev_rec is None or ev_rec.ref.kind != ev_ref.kind or ev_rec.ref.campaign_id != ev_ref.campaign_id:
                return AdaptationAdmission(
                    status="denied",
                    reason_code="source_not_applied",
                    violations=(Violation(code="evidence_not_found", target_ref=ev_ref.source_id),),
                    read_set=snapshot.read_set,
                )
            if ev_rec.status == "question":
                if ground.kind != "interest":
                    return AdaptationAdmission(
                        status="denied",
                        reason_code="source_not_applied",
                        violations=(
                            Violation(
                                code="source_not_applied",
                                target_ref=ev_rec.ref.source_id,
                                actual=ev_rec.status,
                            ),
                        ),
                        read_set=snapshot.read_set,
                    )
            elif ev_rec.status == "rejected":
                return AdaptationAdmission(
                    status="denied",
                    reason_code="source_not_applied",
                    violations=(
                        Violation(
                            code="source_not_applied",
                            target_ref=ev_rec.ref.source_id,
                            actual=ev_rec.status,
                        ),
                    ),
                    read_set=snapshot.read_set,
                )

        if ground.kind == "interest" and ground.confidence == "inferred":
            if len(ground.evidence_refs) < 2:
                return AdaptationAdmission(
                    status="denied",
                    reason_code="source_not_applied",
                    violations=(Violation(code="inferred_interest_requires_multiple_sources"),),
                    read_set=snapshot.read_set,
                )

    # 3. Operations verification
    if len(proposal.operations) > policy.max_operations:
        return AdaptationAdmission(
            status="denied",
            reason_code="operations_limit",
            violations=(Violation(code="operations_limit"),),
            read_set=snapshot.read_set,
        )

    active_offered_thread_ids = {t.id for t in snapshot.threads if t.status in ("offered", "active")}
    new_thread_ids: set[str] = set()

    allowed_operations = (
        set(ACTIVE_OPERATION_KINDS) & set(policy.allowed_operation_kinds) & set(snapshot.permissions.operation_kinds)
    )

    for op_item in proposal.operations:
        if op_item.kind not in allowed_operations:
            return AdaptationAdmission(
                status="denied",
                reason_code="operation_not_available",
                violations=(Violation(code="operation_not_available", target_ref=op_item.kind),),
                read_set=snapshot.read_set,
            )

        spec = next((s for s in _OPERATION_SPECS if s.kind == op_item.kind), None)
        if spec and proposal.source.scope not in spec.scopes:
            return AdaptationAdmission(
                status="denied",
                reason_code="scope_not_allowed",
                violations=(Violation(code="scope_not_allowed", target_ref=op_item.kind),),
                read_set=snapshot.read_set,
            )

        if op_item.kind == "develop_actor_role":
            if op_item.entity_id not in snapshot.actors:
                return AdaptationAdmission(
                    status="denied",
                    reason_code="unverified_data",
                    violations=(Violation(code="unknown_actor", target_ref=op_item.entity_id),),
                    read_set=snapshot.read_set,
                )

        elif op_item.kind == "reveal_fact":
            f_found = any(
                f.ref.subject_id == op_item.fact_ref.subject_id and f.ref.key == op_item.fact_ref.key
                for f in snapshot.facts
            )
            if not f_found:
                return AdaptationAdmission(
                    status="denied",
                    reason_code="unverified_data",
                    violations=(Violation(code="unknown_fact", target_ref=op_item.fact_ref.key),),
                    read_set=snapshot.read_set,
                )

        elif op_item.kind == "upsert_thread":
            t_status = op_item.thread.status
            if t_status in ("offered", "active"):
                t_id = op_item.thread.id
                if t_id not in active_offered_thread_ids:
                    new_thread_ids.add(t_id)
                    total_count = len(active_offered_thread_ids) + len(new_thread_ids)
                    if total_count > policy.max_offered_active_threads:
                        return AdaptationAdmission(
                            status="denied",
                            reason_code="attention_limit",
                            violations=(
                                Violation(
                                    code="attention_limit",
                                    expected=str(policy.max_offered_active_threads),
                                    actual=str(total_count),
                                ),
                            ),
                            read_set=snapshot.read_set,
                        )

        elif op_item.kind == "revise_draft_fact":
            target = op_item.target_ref
            address = f"{target.namespace}:{target.subject_id}:{target.key}"
            perms = snapshot.permissions
            if perms.mutable_fact_addresses and address not in perms.mutable_fact_addresses:
                return AdaptationAdmission(
                    status="denied",
                    reason_code="permission_denied",
                    violations=(Violation(code="immutable_fact_address", target_ref=address),),
                    read_set=snapshot.read_set,
                )
            matching_fact = next(
                (
                    f
                    for f in snapshot.facts
                    if f.ref.namespace == target.namespace
                    and f.ref.subject_id == target.subject_id
                    and f.ref.key == target.key
                ),
                None,
            )
            if matching_fact is not None:
                if matching_fact.freedom == "committed":
                    return AdaptationAdmission(
                        status="denied",
                        reason_code="fact_committed",
                        violations=(Violation(code="fact_committed", target_ref=address),),
                        read_set=snapshot.read_set,
                    )
                if matching_fact.temporal_semantics == "historical":
                    return AdaptationAdmission(
                        status="denied",
                        reason_code="historical_fact_immutable",
                        violations=(Violation(code="historical_fact_immutable", target_ref=address),),
                        read_set=snapshot.read_set,
                    )

    # 4. Novelty & Budgets
    cost = novelty_cost(proposal.operations)

    if proposal.source.scope == "scene":
        scene_limit = snapshot.budgets.get("novelty_scene", policy.max_novelty_scene)
        if cost > scene_limit:
            return AdaptationAdmission(
                status="denied",
                reason_code="novelty_limit",
                violations=(
                    Violation(
                        code="scene_novelty_limit",
                        expected=str(scene_limit),
                        actual=str(cost),
                    ),
                ),
                read_set=snapshot.read_set,
                novelty_cost=cost,
            )

    session_limit = snapshot.budgets.get("novelty_session", policy.max_novelty_session)
    if cost > session_limit:
        return AdaptationAdmission(
            status="denied",
            reason_code="novelty_limit",
            violations=(
                Violation(
                    code="session_novelty_limit",
                    expected=str(session_limit),
                    actual=str(cost),
                ),
            ),
            read_set=snapshot.read_set,
            novelty_cost=cost,
        )

    # 5. Read-set aggregation
    read_refs: list[ReadRef] = list(snapshot.read_set)
    read_ref_ids = {r.id for r in read_refs}

    for ground in proposal.grounds:
        for subj in ground.subject_refs:
            if subj not in read_ref_ids:
                read_refs.append(ReadRef(kind="entity", id=subj))
                read_ref_ids.add(subj)

    for op_item in proposal.operations:
        if op_item.kind == "develop_actor_role":
            if op_item.entity_id not in read_ref_ids:
                read_refs.append(ReadRef(kind="entity", id=op_item.entity_id))
                read_ref_ids.add(op_item.entity_id)
        elif op_item.kind == "upsert_thread":
            if op_item.thread.id not in read_ref_ids:
                read_refs.append(ReadRef(kind="thread", id=op_item.thread.id))
                read_ref_ids.add(op_item.thread.id)
        elif op_item.kind == "revise_draft_fact":
            fact_id = f"{op_item.target_ref.namespace}:{op_item.target_ref.subject_id}:{op_item.target_ref.key}"
            if fact_id not in read_ref_ids:
                read_refs.append(ReadRef(kind="fact", id=fact_id, version=op_item.target_ref.version))
                read_ref_ids.add(fact_id)

    return AdaptationAdmission(
        status="allowed",
        reason_code="ok",
        violations=(),
        read_set=tuple(read_refs),
        novelty_cost=cost,
    )
