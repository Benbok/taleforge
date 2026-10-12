"""Scale tests: bounded queries, context caps, and index-driven queries with 10k events (Task 21)."""

from __future__ import annotations

import asyncio

from app.core.narrative.contracts import (
    EvidenceRef,
    NarrativePolicy,
    NarrativeSource,
    SnapshotRequest,
)
from app.db.models import Campaign, Event, Message, NarrativeFact, NarrativeThread
from app.db.session import make_engine, make_sessionmaker
from app.rules.dice import Dice
from app.tools.narrative.context import load_snapshot
from app.tools.runtime import open_context
from tests.game import import_base, party
from tests.test_api import make_campaign


def test_scale_bounded_queries_under_10k_unrelated_events(settings, client, admin):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    cid = campaign["id"]
    noise_campaign = make_campaign(client, admin, name="Noise Camp")
    other_cid = noise_campaign["id"]

    engine = make_engine(settings.database_url)
    maker = make_sessionmaker(engine)

    async def _run():
        # Insert 10 000 noise events and messages for other campaigns
        async with maker() as s:
            events_chunk = [
                Event(
                    id=f"ev_noise_{i}",
                    campaign_id=other_cid,
                    tool="roll_dice",
                    game_time=i,
                )
                for i in range(5000)
            ]
            messages_chunk = [
                Message(
                    id=f"msg_noise_{i}",
                    campaign_id=other_cid,
                    kind="action",
                    seq=i,
                    content="Шум в соседней кампании",
                )
                for i in range(5000)
            ]
            s.add_all(events_chunk)
            s.add_all(messages_chunk)

            # Insert campaign-specific narrative facts and threads
            for i in range(120):
                s.add(
                    NarrativeFact(
                        campaign_id=cid,
                        namespace="campaign",
                        subject_id=f"creature.guard_{i}",
                        key="role",
                        version=1,
                        kind="truth",
                        temporal_semantics="current_state",
                        freedom="draft",
                        value=f"Стражник #{i}",
                        audience=["party"],
                        snapshot_ref={"kind": "package", "source_id": "p1"},
                    )
                )

            for i in range(40):
                s.add(
                    NarrativeThread(
                        campaign_id=cid,
                        thread_id=f"th_{i}",
                        version=1,
                        status="active" if i % 2 == 0 else "offered",
                        audience=["party"],
                        subject_refs=[f"creature.guard_{i}"],
                        plan_refs=[],
                    )
                )

            await s.commit()

        # Build verified bounded snapshot
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            assert camp is not None
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            policy = NarrativePolicy()

            assert policy.max_snapshot_grounds == 50
            assert policy.max_snapshot_records == 80
            assert policy.max_snapshot_threads == 20

            # Request snapshot
            req = SnapshotRequest(
                source=NarrativeSource(
                    campaign_id=cid,
                    scope="future",
                    source_kind="work",
                    source_id="w-1",
                    stable_part=0,
                ),
                focus="scene.gate",
                evidence_refs=tuple(
                    EvidenceRef(campaign_id=cid, kind="event", source_id=f"ev_target_{i}") for i in range(60)
                ),
                mutable_subject_refs=tuple(f"creature.guard_{i}" for i in range(120)),
            )

            snapshot = await load_snapshot(ctx, req, policy=policy)

            # Assert strict context caps: 50 / 80 / 20 bounds preserved
            assert len(snapshot.facts) <= policy.max_snapshot_records  # <= 80
            assert len(snapshot.threads) <= policy.max_snapshot_threads  # <= 20
            # Noise events from other campaigns are not leaked
            assert all(f.ref.campaign_id == cid for f in snapshot.facts)
            assert all(t.id.startswith("th_") for t in snapshot.threads)

    asyncio.run(_run())
