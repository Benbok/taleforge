import pytest

from app.core.narrative.contracts import (
    EvidenceRef,
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


@pytest.mark.parametrize("kind", ["message", "event", "standing_response", "time_interval"])
def test_missing_or_foreign_evidence_denied(kind, settings, client, admin):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    async def go(s):
        campaign_obj = await s.get(Campaign, cid)
        ctx = await open_context(s, campaign_obj, Dice(), turn_id=None, seat_id=None)

        # 1. Non-existent source_id
        missing_ev = EvidenceRef(campaign_id=cid, kind=kind, source_id="missing-nonexistent-123")
        # 2. Foreign campaign_id
        foreign_ev = EvidenceRef(campaign_id="foreign-camp-999", kind=kind, source_id="foreign-src-123")

        req = SnapshotRequest(
            source=NarrativeSource(campaign_id=cid, scope="scene", source_kind="turn", source_id="t-1", stable_part=0),
            evidence_refs=(missing_ev, foreign_ev),
        )
        snap = await load_snapshot(ctx, req, policy=policy())
        # Neither missing nor foreign evidence should be loaded as applied evidence
        assert len(snap.evidence) == 0

        # Attempting to admit a proposal citing this evidence must be denied
        from app.core.narrative.contracts import Ground
        from app.core.narrative.policy import admit_adaptation
        from tests.narrative_helpers import proposal

        prop_missing = proposal(
            snap,
            grounds=(Ground(kind="divergence", evidence_refs=(missing_ev,), subject_refs=(hero["id"],)),),
        )
        dec_missing = admit_adaptation(snap, prop_missing, policy())
        assert dec_missing.status == "denied"
        assert dec_missing.reason_code == "source_not_applied"

        prop_foreign = proposal(
            snap,
            grounds=(Ground(kind="divergence", evidence_refs=(foreign_ev,), subject_refs=(hero["id"],)),),
        )
        dec_foreign = admit_adaptation(snap, prop_foreign, policy())
        assert dec_foreign.status == "denied"
        assert dec_foreign.reason_code == "source_not_applied"

    run(settings, go)


def test_hidden_evidence_keeps_audience(settings, client, admin):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    async def go(s):
        from app.db.models import Event, Message

        # 1. Private whisper message
        msg = Message(
            campaign_id=cid,
            seq=100,
            kind="whisper",
            visible_to=[hero["id"]],
            content="Секретный шёпот",
        )
        s.add(msg)

        # 2. Hidden domain event
        ev = Event(
            campaign_id=cid,
            tool="roll_check",
            actor_id=hero["id"],
            hidden=True,
            payload={"audience": [hero["id"]]},
        )
        s.add(ev)
        await s.commit()

        campaign_obj = await s.get(Campaign, cid)
        ctx = await open_context(s, campaign_obj, Dice(), turn_id=None, seat_id=None)
        ev_ref_msg = EvidenceRef(campaign_id=cid, kind="message", source_id=msg.id)
        ev_ref_ev = EvidenceRef(campaign_id=cid, kind="event", source_id=ev.id)

        req = SnapshotRequest(
            source=NarrativeSource(campaign_id=cid, scope="scene", source_kind="turn", source_id="t-1", stable_part=0),
            evidence_refs=(ev_ref_msg, ev_ref_ev),
        )
        snap = await load_snapshot(ctx, req, policy=policy())
        assert len(snap.evidence) == 2
        rec_msg = next(r for r in snap.evidence if r.ref.source_id == msg.id)
        rec_ev = next(r for r in snap.evidence if r.ref.source_id == ev.id)
        # Real audience is kept, not replaced with party broadcast
        assert hero["id"] in rec_msg.audience
        assert "party" not in rec_msg.audience
        assert hero["id"] in rec_ev.audience
        assert "party" not in rec_ev.audience

    run(settings, go)


def test_existing_fact_does_not_imply_mutability(settings, client, admin):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    async def go(s):
        f = NarrativeFact(
            campaign_id=cid,
            namespace="module",
            subject_id="creature.guard",
            key="motivation",
            version=1,
            kind="intent",
            temporal_semantics="current_state",
            freedom="draft",
            value="Каноническая мотивация",
            audience=["party"],
            depends_on=[],
            source_refs=[],
            snapshot_ref={"kind": "package", "source_id": "p1", "typed_address": "module:creature.guard:motivation"},
        )
        s.add(f)
        await s.commit()

        campaign_obj = await s.get(Campaign, cid)
        ctx = await open_context(s, campaign_obj, Dice(), turn_id=None, seat_id=None)
        req = SnapshotRequest(
            source=NarrativeSource(campaign_id=cid, scope="future", source_kind="work", source_id="w-1", stable_part=0),
            mutable_subject_refs=("creature.guard",),
        )
        snap = await load_snapshot(ctx, req, policy=policy())
        assert any(fc.ref.subject_id == "creature.guard" for fc in snap.facts)
        # Existing row presence must NOT automatically add it to mutable_fact_addresses
        assert "module:creature.guard:motivation" not in snap.permissions.mutable_fact_addresses

    run(settings, go)
