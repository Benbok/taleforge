"""Tests for narrative commitments and narration reservation (Task 5)."""

import pytest

from app.core.narrative.contracts import (
    FactRef,
    FactState,
    Ground,
    SnapshotRef,
)
from app.core.narrative.facts import revise_draft
from app.db.models import Campaign, Entity, NarrativeFact
from app.db.session import make_engine, make_sessionmaker
from app.rules.dice import Dice
from app.tools.master.knowledge import FactArgs, learn_fact
from app.tools.narrative.commitments import (
    record_commitments,
    reserve_narration_claims,
)
from app.tools.runtime import open_context
from tests.game import import_base, party, run


def test_record_commitments_and_reserve_claims(settings, client, admin):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    snap_ref = SnapshotRef(kind="event", source_id="e1", typed_address="c:1")
    fact_ref = FactRef(
        campaign_id=cid,
        namespace="campaign",
        subject_id="npc-1",
        key="motivation",
        version=1,
        snapshot_ref=snap_ref,
    )

    async def go(s):
        # 1. Add draft fact
        f = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-1",
            key="motivation",
            version=1,
            kind="intent",
            temporal_semantics="current_state",
            freedom="draft",
            value="revenge",
            audience=["party"],
            depends_on=[],
            source_refs=[],
            snapshot_ref={"kind": "event", "source_id": "e1", "typed_address": "c:1"},
        )
        s.add(f)
        await s.commit()

        # 2. Record commitments in ToolContext
        camp_obj = await s.get(Campaign, cid)
        assert camp_obj is not None
        ctx = await open_context(s, camp_obj, Dice(), turn_id="turn-1", seat_id=None)

        sealed = await record_commitments(ctx, (fact_ref,), reason="materialized", snapshot_ref=snap_ref)
        assert fact_ref in sealed

        # Check fact is committed in DB
        updated = await s.get(NarrativeFact, f.id)
        assert updated is not None
        assert updated.freedom == "committed"

        # Calling again on already committed fact does not seal again
        sealed_again = await record_commitments(ctx, (fact_ref,), reason="materialized", snapshot_ref=snap_ref)
        assert len(sealed_again) == 0

    run(settings, go)


def test_reserve_narration_claims(settings, client, admin):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    snap_ref = SnapshotRef(kind="plan", source_id="p1", typed_address="plan:1")
    f_ref = FactRef(
        campaign_id=cid,
        namespace="plan",
        subject_id="boss",
        key="secret_truth",
        version=1,
        snapshot_ref=snap_ref,
    )

    async def go(s):
        f = NarrativeFact(
            campaign_id=cid,
            namespace="plan",
            subject_id="boss",
            key="secret_truth",
            version=1,
            kind="truth",
            temporal_semantics="historical",
            freedom="draft",
            value="he is the brother",
            audience=[],
            depends_on=[],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        s.add(f)
        await s.commit()

    run(settings, go)

    engine = make_engine(settings.database_url)
    maker = make_sessionmaker(engine)

    import asyncio

    async def reserve():
        return await reserve_narration_claims(maker, cid, "turn-1", (f_ref,), ("party",))

    reserved = asyncio.run(reserve())
    assert f_ref in reserved


def test_record_commitments_transitive_dependencies(settings, client, admin):
    """A -> B -> C transitive sealing: all 3 become committed, while independent fact stays draft."""
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    snap_ref = SnapshotRef(kind="event", source_id="e1", typed_address="c:1")
    ref_c = FactRef(
        campaign_id=cid,
        namespace="campaign",
        subject_id="npc-1",
        key="situation_premise",
        version=1,
        snapshot_ref=snap_ref,
    )
    ref_b = FactRef(
        campaign_id=cid, namespace="campaign", subject_id="npc-1", key="relationship", version=1, snapshot_ref=snap_ref
    )
    ref_a = FactRef(
        campaign_id=cid, namespace="campaign", subject_id="npc-1", key="role", version=1, snapshot_ref=snap_ref
    )

    async def go(s):
        fc = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-1",
            key="situation_premise",
            version=1,
            kind="truth",
            temporal_semantics="current_state",
            freedom="draft",
            value="In tavern",
            audience=["party"],
            depends_on=[],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        fb = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-1",
            key="relationship",
            version=1,
            kind="truth",
            temporal_semantics="current_state",
            freedom="draft",
            value="Friend of barkeep",
            audience=["party"],
            depends_on=[ref_c.model_dump()],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        fa = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-1",
            key="role",
            version=1,
            kind="truth",
            temporal_semantics="current_state",
            freedom="draft",
            value="Guard",
            audience=["party"],
            depends_on=[ref_b.model_dump()],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        fd = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-1",
            key="motivation",
            version=1,
            kind="intent",
            temporal_semantics="current_state",
            freedom="draft",
            value="Wants money",
            audience=[],
            depends_on=[],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        s.add_all([fc, fb, fa, fd])
        await s.commit()

        camp_obj = await s.get(Campaign, cid)
        ctx = await open_context(s, camp_obj, Dice(), turn_id="turn-1", seat_id=None)

        sealed = await record_commitments(ctx, (ref_a,), reason="materialized", snapshot_ref=snap_ref)
        sealed_keys = {(r.namespace, r.subject_id, r.key) for r in sealed}
        assert ("campaign", "npc-1", "role") in sealed_keys
        assert ("campaign", "npc-1", "relationship") in sealed_keys
        assert ("campaign", "npc-1", "situation_premise") in sealed_keys

        assert (await s.get(NarrativeFact, fa.id)).freedom == "committed"
        assert (await s.get(NarrativeFact, fb.id)).freedom == "committed"
        assert (await s.get(NarrativeFact, fc.id)).freedom == "committed"
        assert (await s.get(NarrativeFact, fd.id)).freedom == "draft"

    run(settings, go)


def test_record_commitments_violations_atomic_rollback(settings, client, admin):
    """Violations (cycle, missing, foreign, stale, limits) cause atomic refusal without partial seal."""
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    snap_ref = SnapshotRef(kind="event", source_id="e1", typed_address="c:1")
    ref_x = FactRef(
        campaign_id=cid, namespace="campaign", subject_id="npc-v", key="role", version=1, snapshot_ref=snap_ref
    )
    ref_y = FactRef(
        campaign_id=cid, namespace="campaign", subject_id="npc-v", key="relationship", version=1, snapshot_ref=snap_ref
    )

    async def go(s):
        # 1. Cycle: X -> Y -> X
        fx = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-v",
            key="role",
            version=1,
            kind="truth",
            temporal_semantics="current_state",
            freedom="draft",
            value="Guard",
            audience=[],
            depends_on=[ref_y.model_dump()],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        fy = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-v",
            key="relationship",
            version=1,
            kind="truth",
            temporal_semantics="current_state",
            freedom="draft",
            value="Ally",
            audience=[],
            depends_on=[ref_x.model_dump()],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        s.add_all([fx, fy])
        await s.commit()

        camp_obj = await s.get(Campaign, cid)
        ctx = await open_context(s, camp_obj, Dice(), turn_id="turn-1", seat_id=None)

        with pytest.raises(ValueError, match="dependency_cycle"):
            await record_commitments(ctx, (ref_x,), reason="cycle_test", snapshot_ref=snap_ref)

        # Neither should be committed
        assert (await s.get(NarrativeFact, fx.id)).freedom == "draft"
        assert (await s.get(NarrativeFact, fy.id)).freedom == "draft"

        # 2. Missing dependency
        dep_ghost = {"campaign_id": cid, "namespace": "campaign", "subject_id": "ghost", "key": "role", "version": 1}
        f_missing = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-v",
            key="motivation",
            version=1,
            kind="intent",
            temporal_semantics="current_state",
            freedom="draft",
            value="Secret",
            audience=[],
            depends_on=[dep_ghost],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        s.add(f_missing)
        await s.commit()

        ref_missing = FactRef(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-v",
            key="motivation",
            version=1,
            snapshot_ref=snap_ref,
        )
        with pytest.raises(ValueError, match="missing_dependency"):
            await record_commitments(ctx, (ref_missing,), reason="missing_test", snapshot_ref=snap_ref)
        assert (await s.get(NarrativeFact, f_missing.id)).freedom == "draft"

        # 3. Foreign campaign ref
        ref_foreign = FactRef(
            campaign_id="c-foreign",
            namespace="campaign",
            subject_id="npc-v",
            key="role",
            version=1,
            snapshot_ref=snap_ref,
        )
        with pytest.raises(ValueError, match="foreign_campaign"):
            await record_commitments(ctx, (ref_foreign,), reason="foreign_test", snapshot_ref=snap_ref)

        # 4. Stale version (ref has v2, db has v1)
        ref_stale = FactRef(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-v",
            key="role",
            version=2,
            snapshot_ref=snap_ref,
        )
        with pytest.raises(ValueError, match="stale_fact_version"):
            await record_commitments(ctx, (ref_stale,), reason="stale_test", snapshot_ref=snap_ref)

    run(settings, go)


def test_draft_only_sealing_and_no_subsequent_retcon(settings, client, admin):
    """Draft_only can become committed upon introduction, preventing subsequent retcons."""
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    snap_ref = SnapshotRef(kind="package", source_id="pkg-1", typed_address="mod:draft")
    ref_draft_only = FactRef(
        campaign_id=cid, namespace="module", subject_id="npc-draft", key="role", version=1, snapshot_ref=snap_ref
    )

    async def go(s):
        f = NarrativeFact(
            campaign_id=cid,
            namespace="module",
            subject_id="npc-draft",
            key="role",
            version=1,
            kind="truth",
            temporal_semantics="draft_only",
            freedom="draft",
            value="Initial placeholder",
            audience=["party"],
            depends_on=[],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        s.add(f)
        await s.commit()

        camp_obj = await s.get(Campaign, cid)
        ctx = await open_context(s, camp_obj, Dice(), turn_id="turn-1", seat_id=None)

        # 1. Sealing draft_only is allowed
        sealed = await record_commitments(ctx, (ref_draft_only,), reason="intro_sealing", snapshot_ref=snap_ref)
        assert ref_draft_only in sealed
        updated = await s.get(NarrativeFact, f.id)
        assert updated.freedom == "committed"

        # 2. Subsequent retcon via revise_draft is rejected because it is committed
        state = FactState(
            ref=ref_draft_only,
            kind="truth",
            temporal_semantics="draft_only",
            freedom="committed",
            value="Initial placeholder",
            audience=("party",),
            depends_on=(),
        )
        ground = Ground(kind="divergence", evidence_refs=(), subject_refs=())
        rev = revise_draft(state, "Altered role", ground)
        assert "fact_committed" in rev.violations
        assert rev.after is None

    run(settings, go)


def test_string_refs_resolution(settings, client, admin):
    """Strings like 'namespace:subject_id:key' are resolved by the server to actual FactRefs."""
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    snap_ref = SnapshotRef(kind="plan", source_id="p-1", typed_address="p:1")

    async def go(s):
        f = NarrativeFact(
            campaign_id=cid,
            namespace="plan",
            subject_id="npc-str",
            key="motivation",
            version=1,
            kind="intent",
            temporal_semantics="current_state",
            freedom="draft",
            value="Greed",
            audience=[],
            depends_on=[],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        s.add(f)
        await s.commit()

        camp_obj = await s.get(Campaign, cid)
        ctx = await open_context(s, camp_obj, Dice(), turn_id="turn-1", seat_id=None)

        # Pass 3-part string
        sealed = await record_commitments(
            ctx,
            ("plan:npc-str:motivation",),
            reason="string_seal",
            snapshot_ref=snap_ref,
        )
        assert len(sealed) == 1
        assert sealed[0].subject_id == "npc-str"
        assert (await s.get(NarrativeFact, f.id)).freedom == "committed"

    run(settings, go)


def test_learn_fact_seals_only_exact_used_refs(settings, client, admin):
    """learn_fact commits only exact used_fact_refs; unrelated motives/secrets remain draft."""
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    snap_ref = SnapshotRef(kind="event", source_id="e1", typed_address="c:1")

    async def go(s):
        # Create entity in world
        boss = Entity(
            id="boss-1",
            campaign_id=cid,
            kind="npc",
            name="Староста",
            location_id="loc-tavern",
        )
        s.add(boss)

        f_role = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="boss-1",
            key="role",
            version=1,
            kind="truth",
            temporal_semantics="current_state",
            freedom="draft",
            value="Elder",
            audience=["party"],
            depends_on=[],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        f_secret = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="boss-1",
            key="secret_truth",
            version=1,
            kind="truth",
            temporal_semantics="historical",
            freedom="draft",
            value="Cultist leader",
            audience=[],
            depends_on=[],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        f_motive = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="boss-1",
            key="motivation",
            version=1,
            kind="intent",
            temporal_semantics="current_state",
            freedom="draft",
            value="Summon demon",
            audience=[],
            depends_on=[],
            source_refs=[],
            snapshot_ref=snap_ref.model_dump(),
        )
        s.add_all([f_role, f_secret, f_motive])
        await s.commit()

        camp_obj = await s.get(Campaign, cid)
        ctx = await open_context(s, camp_obj, Dice(), turn_id="turn-1", seat_id=None)

        # 1. Normal learn_fact without used_fact_refs does NOT commit any narrative facts!
        await learn_fact(
            ctx,
            FactArgs(
                character_ids=[hero["id"]],
                subject_id="boss-1",
                fact="Староста боится леса",
            ),
        )
        assert (await s.get(NarrativeFact, f_role.id)).freedom == "draft"
        assert (await s.get(NarrativeFact, f_secret.id)).freedom == "draft"
        assert (await s.get(NarrativeFact, f_motive.id)).freedom == "draft"

        # 2. Calling learn_fact with exact used_fact_refs commits ONLY that fact!
        await learn_fact(
            ctx,
            FactArgs(
                character_ids=[hero["id"]],
                subject_id="boss-1",
                fact="Староста действительно староста",
                used_fact_refs=["campaign:boss-1:role"],
            ),
        )
        assert (await s.get(NarrativeFact, f_role.id)).freedom == "committed"
        assert (await s.get(NarrativeFact, f_secret.id)).freedom == "draft"
        assert (await s.get(NarrativeFact, f_motive.id)).freedom == "draft"

    run(settings, go)
