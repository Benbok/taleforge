import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.narrative.contracts import (
    AdaptationAdmission,
    AdaptationProposal,
    AdaptationResult,
    EvidenceRecord,
    EvidenceRef,
    FactRef,
    FactState,
    FrontRef,
    FrontView,
    FuturePlanEdit,
    FutureSituationPatch,
    Ground,
    LocalRef,
    NarrativePermissions,
    NarrativeSnapshot,
    NarrativeSource,
    Operation,
    PublicEffect,
    QuestionState,
    ReadRef,
    SnapshotRef,
    SnapshotRequest,
    ThreadState,
    VersionSet,
    Violation,
    WorkClaim,
)
from app.core.narrative.ports import NarrativeApplier, NarrativeAuthor, NarrativeReader
from tests.narrative_helpers import (
    fact,
    op,
    policy,
    proposal,
    snapshot,
    thread,
)


def test_proposal_roundtrip_without_actor_id():
    snap = snapshot()
    item = proposal(snap)
    assert AdaptationProposal.model_validate_json(item.model_dump_json()) == item
    assert "actor_id" not in item.source.model_dump()
    assert item.schema_version == 1


def test_contracts_forbid_extra_fields():
    with pytest.raises(ValidationError):
        NarrativeSource(
            campaign_id="c1",
            scope="future",
            source_kind="work",
            source_id="w1",
            stable_part=0,
            extra_field="disallowed",  # type: ignore[call-arg]
        )


def test_contracts_are_frozen():
    src = NarrativeSource(
        campaign_id="c1",
        scope="future",
        source_kind="work",
        source_id="w1",
        stable_part=0,
    )
    with pytest.raises(ValidationError):
        src.stable_part = 1  # type: ignore[misc]


def test_source_key_format():
    src = NarrativeSource(
        campaign_id="camp-xyz",
        scope="scene",
        source_kind="turn",
        source_id="turn-42",
        stable_part=2,
    )
    assert src.source_key() == "camp-xyz:turn:turn-42:2"


def test_unknown_operation_kind_rejected():
    with pytest.raises(ValidationError):
        op(kind="arbitrary_cheat_operation", foo="bar")


def test_all_spec_operation_kinds_constructible():
    fact_inst = fact()
    f_ref = fact_inst.ref
    front_ref = FrontRef(campaign_id="c1", source_kind="antagonist", source_id="a1")
    thread_inst = thread()

    ops = [
        op("add_campaign_fact", fact=fact_inst),
        op("revise_draft_fact", target_ref=f_ref, new_value="v2"),
        op("develop_actor_role", entity_id="e1", new_role="ally"),
        op(
            "introduce_actor",
            actor_slot="slot_1",
            template_id="tmpl_guard",
            place_ref="tavern",
            attitude="neutral",
            public_description="A weary guard",
            mode="sketch",
        ),
        op(
            "revise_future_situation",
            patch=FutureSituationPatch(
                edits=(
                    FuturePlanEdit(
                        kind="update_open_node",
                        act_id="act_1",
                        node_id="node_2",
                        fields={"summary": "New route"},
                    ),
                )
            ),
        ),
        op("change_front_intent", front_ref=front_ref, new_intent="Hold position"),
        op("advance_front", front_ref=front_ref, steps=1),
        op("upsert_thread", thread=thread_inst),
        op("transition_thread", thread_id="t1", target_status="active"),
        op("reveal_fact", fact_ref=f_ref, audience=("party",)),
        op("settle_standing_response", response_id="resp-1", settled_effects=()),
    ]
    assert len(ops) == 11
    for o in ops:
        assert isinstance(o, (Operation.__args__))  # type: ignore[attr-defined]


def test_all_contract_types_instantiable():
    ev_ref = EvidenceRef(campaign_id="c1", kind="message", source_id="m1")
    ev_rec = EvidenceRecord(ref=ev_ref, status="applied", game_time=100)
    snap_ref = SnapshotRef(kind="plan", source_id="p1", typed_address="act:1")
    fact_ref = FactRef(
        campaign_id="c1",
        namespace="plan",
        subject_id="s1",
        key="role",
        snapshot_ref=snap_ref,
    )
    fact_state = FactState(
        ref=fact_ref,
        kind="truth",
        temporal_semantics="historical",
        freedom="committed",
        value="hero",
    )
    front_ref = FrontRef(campaign_id="c1", source_kind="front", source_id="f1")
    front_view = FrontView(ref=front_ref, owner_ref="boss", goal="destroy")
    thread_state = ThreadState(id="t1")
    version_set = VersionSet(
        world_revision=1,
        plan_version=1,
        narrative_revision=1,
        policy_version=1,
    )
    violation = Violation(code="test_err")
    local_ref = LocalRef(actor_slot="s1")
    permissions = NarrativePermissions()
    question = QuestionState(id="q1", text="Will they ally?")
    read_ref = ReadRef(kind="fact", id="f1")
    ground = Ground(kind="consequence", evidence_refs=(ev_ref,))
    req = SnapshotRequest(source=NarrativeSource(campaign_id="c1", scope="scene", source_kind="turn", source_id="t1"))
    pol = policy()
    admission = AdaptationAdmission(status="allowed", reason_code="ok")
    public_eff = PublicEffect(kind="cue", description="Desc")
    res = AdaptationResult(status="applied", reason_code="ok")
    claim = WorkClaim(
        work_id="w1",
        campaign_id="c1",
        source=req.source,
        proposal_id="p1",
        lease_token="tkn",
        lease_until=datetime.now(UTC),
        session_budget_ref="sbr",
    )

    assert ev_rec.game_time == 100
    assert fact_state.value == "hero"
    assert front_view.goal == "destroy"
    assert thread_state.id == "t1"
    assert version_set.operation_schema_version == 1
    assert violation.code == "test_err"
    assert local_ref.actor_slot == "s1"
    assert permissions.anchors == ()
    assert question.status == "open"
    assert read_ref.kind == "fact"
    assert ground.kind == "consequence"
    assert pol.mode == "adaptive"
    assert admission.status == "allowed"
    assert public_eff.kind == "cue"
    assert res.status == "applied"
    assert claim.phase == "author"


def test_ports_contract():
    class DummyReader:
        async def snapshot(self, request: SnapshotRequest) -> NarrativeSnapshot:
            raise NotImplementedError

    class DummyAuthor:
        async def propose(self, snap: NarrativeSnapshot) -> AdaptationProposal:
            raise NotImplementedError

    class DummyApplier:
        async def apply(self, prop: AdaptationProposal) -> AdaptationResult:
            raise NotImplementedError

    assert issubclass(DummyReader, NarrativeReader)
    assert issubclass(DummyAuthor, NarrativeAuthor)
    assert issubclass(DummyApplier, NarrativeApplier)


def test_domain_narrative_imports_have_no_infrastructure():
    domain_dir = Path("app/core/narrative")
    forbidden_prefixes = (
        "app.db",
        "app.tools",
        "app.agents",
        "sqlalchemy",
        "fastapi",
        "litellm",
        "openai",
        "anthropic",
    )
    for py_file in domain_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in forbidden_prefixes:
                        assert not alias.name.startswith(forbidden), f"Forbidden import '{alias.name}' in {py_file}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for forbidden in forbidden_prefixes:
                    assert not mod.startswith(forbidden), f"Forbidden import from '{mod}' in {py_file}"
