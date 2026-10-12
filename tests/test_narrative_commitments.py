"""Tests for narrative commitments and narration reservation (Task 5)."""


from app.core.narrative.contracts import (
    FactRef,
    SnapshotRef,
)
from app.db.models import Campaign, NarrativeFact
from app.db.session import make_engine, make_sessionmaker
from app.rules.dice import Dice
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
