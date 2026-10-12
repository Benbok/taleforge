"""Tests for fact sealing domain logic."""


from app.core.narrative.contracts import (
    FactRef,
    FactState,
    SnapshotRef,
)
from app.core.narrative.facts import seal_facts
from tests.narrative_helpers import fact


def spatial_fact_fixture() -> tuple[tuple[FactState, ...], FactRef, FactRef]:
    room_snap = SnapshotRef(kind="package", source_id="srd", typed_address="loc:crypt:room_1")
    room_ref = FactRef(
        campaign_id="camp-1",
        namespace="module",
        subject_id="room_1",
        key="situation_premise",
        version=1,
        snapshot_ref=room_snap,
    )
    room_fact = fact(
        ref=room_ref,
        kind="truth",
        temporal_semantics="historical",
        freedom="draft",
        value="Затопленный зал с колоннами",
    )

    motive_snap = SnapshotRef(kind="plan", source_id="npc_guard", typed_address="plan:npc:npc_guard:want")
    motive_ref = FactRef(
        campaign_id="camp-1",
        namespace="plan",
        subject_id="npc_guard",
        key="motivation",
        version=1,
        snapshot_ref=motive_snap,
    )
    motive_fact = fact(
        ref=motive_ref,
        kind="intent",
        temporal_semantics="current_state",
        freedom="draft",
        value="Найти брата",
    )

    return (room_fact, motive_fact), room_ref, motive_ref


def test_spatial_producer_seals_only_used_fact_and_dependencies():
    facts, room_ref, motive_ref = spatial_fact_fixture()
    result = seal_facts(facts, (room_ref,))
    assert room_ref in result.refs
    assert motive_ref not in result.refs
    assert result.violations == ()


def test_seal_facts_transitive_dependencies():
    snap = SnapshotRef(kind="event", source_id="e1", typed_address="a:1")
    f_root_ref = FactRef(campaign_id="c1", namespace="campaign", subject_id="s1", key="role", snapshot_ref=snap)
    f_dep1_ref = FactRef(campaign_id="c1", namespace="campaign", subject_id="s2", key="role", snapshot_ref=snap)
    f_dep2_ref = FactRef(campaign_id="c1", namespace="campaign", subject_id="s3", key="role", snapshot_ref=snap)

    f_dep2 = fact(ref=f_dep2_ref, depends_on=())
    f_dep1 = fact(ref=f_dep1_ref, depends_on=(f_dep2_ref,))
    f_root = fact(ref=f_root_ref, depends_on=(f_dep1_ref,))

    result = seal_facts((f_root, f_dep1, f_dep2), (f_root_ref,))
    assert result.violations == ()
    assert f_root_ref in result.refs
    assert f_dep1_ref in result.refs
    assert f_dep2_ref in result.refs


def test_seal_facts_detects_dependency_cycle():
    snap = SnapshotRef(kind="event", source_id="e1", typed_address="a:1")
    f1_ref = FactRef(campaign_id="c1", namespace="campaign", subject_id="s1", key="role", snapshot_ref=snap)
    f2_ref = FactRef(campaign_id="c1", namespace="campaign", subject_id="s2", key="role", snapshot_ref=snap)

    f1 = fact(ref=f1_ref, depends_on=(f2_ref,))
    f2 = fact(ref=f2_ref, depends_on=(f1_ref,))

    result = seal_facts((f1, f2), (f1_ref,))
    assert result.refs == ()
    assert "dependency_cycle" in result.violations


def test_seal_facts_enforces_max_dependencies():
    snap = SnapshotRef(kind="event", source_id="e1", typed_address="a:1")
    dep_refs = tuple(
        FactRef(campaign_id="c1", namespace="campaign", subject_id=f"dep_{i}", key="role", snapshot_ref=snap)
        for i in range(17)
    )
    deps = tuple(fact(ref=r) for r in dep_refs)
    root_ref = FactRef(campaign_id="c1", namespace="campaign", subject_id="root", key="role", snapshot_ref=snap)
    root = fact(ref=root_ref, depends_on=dep_refs)

    result = seal_facts((root, *deps), (root_ref,), max_dependencies=16)
    assert result.refs == ()
    assert "max_dependencies_exceeded" in result.violations


def test_seal_facts_enforces_max_visited():
    snap = SnapshotRef(kind="event", source_id="e1", typed_address="a:1")
    # A chain of 65 facts
    refs = [
        FactRef(campaign_id="c1", namespace="campaign", subject_id=f"s_{i}", key="role", snapshot_ref=snap)
        for i in range(65)
    ]
    facts_list = []
    for i in range(64):
        facts_list.append(fact(ref=refs[i], depends_on=(refs[i + 1],)))
    facts_list.append(fact(ref=refs[64], depends_on=()))

    result = seal_facts(tuple(facts_list), (refs[0],), max_visited=64)
    assert result.refs == ()
    assert "max_visited_exceeded" in result.violations
