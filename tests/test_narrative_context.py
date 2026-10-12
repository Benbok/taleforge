"""Tests for narrative snapshot builder and DbNarrativeReader."""

from app.core.narrative.contracts import (
    NarrativeSource,
    SnapshotRequest,
)
from app.core.narrative.ports import NarrativeReader
from app.db.models import Campaign, NarrativeFact
from app.db.session import make_engine, make_sessionmaker
from app.rules.dice import Dice
from app.tools.narrative.context import load_snapshot
from app.tools.narrative.reader import DbNarrativeReader
from app.tools.runtime import open_context
from tests.game import import_base, party, run
from tests.narrative_helpers import policy


def test_load_snapshot_and_db_reader(settings, client, admin):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    async def go(s):
        # 1. Add secret and fact
        f = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-1",
            key="role",
            version=1,
            kind="truth",
            temporal_semantics="current_state",
            freedom="draft",
            value="allied_informant",
            audience=["party"],
            depends_on=[],
            source_refs=[],
            snapshot_ref={"kind": "event", "source_id": "e1", "typed_address": "c:1"},
        )
        s.add(f)
        await s.commit()

        # 2. Open ToolContext and test load_snapshot
        req = SnapshotRequest(
            source=NarrativeSource(
                campaign_id=cid,
                scope="future",
                source_kind="work",
                source_id="w-1",
                stable_part=0,
            ),
            mutable_subject_refs=("npc-1",),
        )

        campaign_obj = await s.get(Campaign, cid)
        assert campaign_obj is not None
        ctx = await open_context(s, campaign_obj, Dice(), turn_id=None, seat_id=None)
        snap = await load_snapshot(ctx, req, policy=policy())
        assert snap.source.campaign_id == cid
        assert snap.proposal_id != ""
        assert any(fc.ref.subject_id == "npc-1" for fc in snap.facts)
        assert len(snap.read_set) > 0

    run(settings, go)


def test_db_narrative_reader_conformance(settings):
    engine = make_engine(settings.database_url)
    maker = make_sessionmaker(engine)
    reader = DbNarrativeReader(maker, policy_provider=policy)
    assert isinstance(reader, NarrativeReader)
