from app.core.narrative.contracts import (
    EvidenceRecord,
    EvidenceRef,
    FactRef,
    FrontRef,
    FuturePlanEdit,
    FutureSituationPatch,
    Ground,
    NarrativeSource,
    SnapshotRef,
)
from app.core.narrative.policy import admit_adaptation, novelty_cost, operation_specs
from tests.narrative_helpers import (
    fact,
    op,
    policy,
    proposal,
    snapshot,
    thread,
)


def test_question_cannot_authorize_completed_alliance():
    snap = snapshot(evidence_status="question")
    # Ground references the question evidence with relationship kind
    item = proposal(
        snap,
        grounds=(
            Ground(
                kind="relationship",
                evidence_refs=(snap.evidence[0].ref,),
                subject_refs=("npc-1",),
                confidence="explicit",
            ),
        ),
    )
    decision = admit_adaptation(snap, item, policy())
    assert decision.status == "denied"
    assert decision.reason_code == "source_not_applied"


def test_valid_proposal_allowed():
    snap = snapshot()
    prop = proposal(
        snap,
        operations=(op("develop_actor_role", entity_id="npc-1", new_role="allied_informant"),),
    )
    decision = admit_adaptation(snap, prop, policy())
    assert decision.status == "allowed"
    assert decision.reason_code == "ok"
    assert len(decision.read_set) > 0


def test_forged_server_identity_rejected():
    snap = snapshot()
    forged_source = NarrativeSource(
        campaign_id="other-camp",
        scope="future",
        source_kind="work",
        source_id="work-1",
        stable_part=0,
    )
    prop = proposal(snap, source=forged_source)
    decision = admit_adaptation(snap, prop, policy())
    assert decision.status == "denied"
    assert decision.reason_code == "unknown_source"


def test_operations_limit_exceeded():
    snap = snapshot()
    # 9 operations when max is 8
    ops = tuple(op("develop_actor_role", entity_id="npc-1", new_role=f"role_{i}") for i in range(9))
    prop = proposal(snap, operations=ops)
    decision = admit_adaptation(snap, prop, policy())
    assert decision.status == "denied"
    assert decision.reason_code == "operations_limit"


def test_novelty_scene_limit_exceeded():
    snap = snapshot(
        source=NarrativeSource(
            campaign_id="camp-1",
            scope="scene",
            source_kind="turn",
            source_id="t1",
            stable_part=0,
        ),
        budgets={"novelty_scene": 1, "novelty_session": 10},
    )
    # Add 2 campaign facts (cost 2, budget left 1)
    f1 = fact(
        ref=FactRef(
            campaign_id="camp-1",
            namespace="campaign",
            subject_id="npc-1",
            key="role",
            snapshot_ref=SnapshotRef(kind="event", source_id="e1", typed_address="c:1"),
        )
    )
    f2 = fact(
        ref=FactRef(
            campaign_id="camp-1",
            namespace="campaign",
            subject_id="npc-1",
            key="relationship",
            snapshot_ref=SnapshotRef(kind="event", source_id="e2", typed_address="c:2"),
        )
    )
    prop = proposal(
        snap,
        operations=(
            op("add_campaign_fact", fact=f1),
            op("add_campaign_fact", fact=f2),
        ),
    )
    decision = admit_adaptation(snap, prop, policy())
    assert decision.status == "denied"
    assert decision.reason_code == "novelty_limit"


def test_attention_limit_at_5_offered_active_threads():
    # 5 already active/offered threads in snapshot
    threads = tuple(thread(id=f"t-{i}", status="active") for i in range(5))
    snap = snapshot(threads=threads)
    # Trying to upsert a 6th new thread
    new_t = thread(id="t-new", status="offered")
    prop = proposal(snap, operations=(op("upsert_thread", thread=new_t),))
    decision = admit_adaptation(snap, prop, policy())
    assert decision.status == "denied"
    assert decision.reason_code == "attention_limit"


def test_inferred_interest_requires_two_sources():
    ev1 = EvidenceRecord(
        ref=EvidenceRef(campaign_id="camp-1", kind="message", source_id="m1"),
        status="applied",
        game_time=100,
    )
    snap = snapshot(evidence=(ev1,))
    prop = proposal(
        snap,
        grounds=(
            Ground(
                kind="interest",
                evidence_refs=(ev1.ref,),
                subject_refs=("npc-1",),
                confidence="inferred",
            ),
        ),
    )
    decision = admit_adaptation(snap, prop, policy())
    assert decision.status == "denied"
    assert decision.reason_code == "source_not_applied"


def test_explicit_interest_with_single_source_allowed():
    ev1 = EvidenceRecord(
        ref=EvidenceRef(campaign_id="camp-1", kind="message", source_id="m1"),
        status="applied",
        game_time=100,
    )
    snap = snapshot(evidence=(ev1,))
    prop = proposal(
        snap,
        grounds=(
            Ground(
                kind="interest",
                evidence_refs=(ev1.ref,),
                subject_refs=("npc-1",),
                confidence="explicit",
            ),
        ),
    )
    decision = admit_adaptation(snap, prop, policy())
    assert decision.status == "allowed"


def test_operation_not_available_for_gate_a():
    snap = snapshot()
    prop = proposal(
        snap,
        operations=(
            op(
                "advance_front",
                front_ref=FrontRef(campaign_id="camp-1", source_kind="front", source_id="f1"),
                steps=1,
            ),
        ),
    )
    decision = admit_adaptation(snap, prop, policy())
    assert decision.status == "denied"
    assert decision.reason_code == "operation_not_available"


def test_scope_mismatch_denied():
    snap = snapshot(
        source=NarrativeSource(
            campaign_id="camp-1",
            scope="scene",
            source_kind="turn",
            source_id="t1",
            stable_part=0,
        ),
    )
    prop = proposal(
        snap,
        operations=(
            op(
                "revise_future_situation",
                patch=FutureSituationPatch(
                    edits=(
                        FuturePlanEdit(
                            kind="update_open_node",
                            act_id="a1",
                            node_id="n1",
                        ),
                    )
                ),
            ),
        ),
    )
    decision = admit_adaptation(snap, prop, policy())
    assert decision.status == "denied"
    assert decision.reason_code == "scope_not_allowed"


def test_future_with_pending_narration_deferred():
    snap = snapshot(
        source=NarrativeSource(
            campaign_id="camp-1",
            scope="future",
            source_kind="work",
            source_id="w1",
            stable_part=0,
        ),
        budgets={"pending_narration": 1},
    )
    prop = proposal(snap)
    decision = admit_adaptation(snap, prop, policy())
    assert decision.status == "deferred"
    assert decision.reason_code == "narration_pending"


def test_operation_specs_and_novelty_cost():
    specs = operation_specs()
    assert len(specs) >= 11
    kinds = {s.kind for s in specs}
    assert "add_campaign_fact" in kinds
    assert "develop_actor_role" in kinds

    f = fact()
    ops = (
        op("add_campaign_fact", fact=f),
        op("develop_actor_role", entity_id="npc-1", new_role="ally"),
    )
    assert novelty_cost(ops) == 1


def test_empty_policy_denies_operation():
    snap = snapshot()
    prop = proposal(
        snap,
        operations=(op("develop_actor_role", entity_id="npc-1", new_role="ally"),),
    )
    pol = policy().model_copy(update={"allowed_operation_kinds": ()})
    decision = admit_adaptation(snap, prop, pol)
    assert decision.status == "denied"
    assert decision.reason_code == "operation_not_available"


def test_module_disallows_operation():
    from app.core.narrative.contracts import NarrativePermissions

    snap = snapshot(
        permissions=NarrativePermissions(
            operation_kinds=("revise_draft_fact",),
        )
    )
    prop = proposal(
        snap,
        operations=(op("develop_actor_role", entity_id="npc-1", new_role="ally"),),
    )
    decision = admit_adaptation(snap, prop, policy())
    assert decision.status == "denied"
    assert decision.reason_code == "operation_not_available"


def test_question_is_interest_not_alliance():
    snap = snapshot(evidence_status="question")
    # 1. Question used for relationship (alliance) -> DENIED
    prop_alliance = proposal(
        snap,
        grounds=(
            Ground(
                kind="relationship",
                evidence_refs=(snap.evidence[0].ref,),
                subject_refs=("npc-1",),
                confidence="explicit",
            ),
        ),
        operations=(op("develop_actor_role", entity_id="npc-1", new_role="ally"),),
    )
    dec_alliance = admit_adaptation(snap, prop_alliance, policy())
    assert dec_alliance.status == "denied"
    assert dec_alliance.reason_code == "source_not_applied"

    # 2. Question used for interest -> ALLOWED as an inquiry basis
    prop_interest = proposal(
        snap,
        grounds=(
            Ground(
                kind="interest",
                evidence_refs=(snap.evidence[0].ref,),
                subject_refs=("npc-1",),
                confidence="explicit",
            ),
        ),
        operations=(op("develop_actor_role", entity_id="npc-1", new_role="ally"),),
    )
    dec_interest = admit_adaptation(snap, prop_interest, policy())
    assert dec_interest.status == "allowed"
    assert dec_interest.reason_code == "ok"
