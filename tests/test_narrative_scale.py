"""Scale tests: bounded queries, context caps, and index-driven queries with 10k events (Task 21)."""

from __future__ import annotations

import asyncio

from sqlalchemy import event, select, text

from app.core.narrative.contracts import (
    EvidenceRef,
    NarrativePolicy,
    NarrativeSource,
    SnapshotRequest,
)
from app.db.models import Campaign, CampaignSecret, Event, Message, NarrativeFact, NarrativeThread
from app.db.session import make_engine, make_sessionmaker
from app.rules.dice import Dice
from app.tools.narrative.context import load_snapshot
from app.tools.runtime import open_context
from tests.game import import_base, party
from tests.test_api import make_campaign


def test_scale_bounded_queries_under_10k_history(settings, client, admin):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    cid = campaign["id"]
    noise_campaign = make_campaign(client, admin, name="Noise Camp")
    other_cid = noise_campaign["id"]

    engine = make_engine(settings.database_url)
    maker = make_sessionmaker(engine)

    async def _run():
        # 10 000 historical rows belong to the active campaign; a smaller
        # neighboring campaign proves that the campaign predicate is retained.
        async with maker() as s:
            events_chunk = [
                Event(
                    id=f"ev_noise_{i}",
                    campaign_id=cid,
                    tool="roll_dice",
                    game_time=i,
                )
                for i in range(5000)
            ]
            messages_chunk = [
                Message(
                    id=f"msg_noise_{i}",
                    campaign_id=cid,
                    kind="action",
                    seq=100_000 + i,
                    content="Шум в соседней кампании",
                )
                for i in range(5000)
            ]
            target_events = [
                Event(
                    id=f"ev_target_{i}",
                    campaign_id=cid,
                    tool="roll_check",
                    actor_id=_hero["id"],
                    game_time=10_000 + i,
                )
                for i in range(30)
            ]
            target_messages = [
                Message(
                    id=f"msg_target_{i}",
                    campaign_id=cid,
                    kind="speech",
                    seq=10_000 + i,
                    content=f"Выбор игроков #{i}",
                )
                for i in range(30)
            ]
            foreign_events = [
                Event(id=f"ev_foreign_{i}", campaign_id=other_cid, tool="roll_dice", game_time=i) for i in range(100)
            ]
            foreign_messages = [
                Message(
                    id=f"msg_foreign_{i}",
                    campaign_id=other_cid,
                    kind="action",
                    seq=100_000 + i,
                    content="Чужой шум",
                )
                for i in range(100)
            ]
            s.add_all(
                events_chunk + messages_chunk + target_events + target_messages + foreign_events + foreign_messages
            )

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
            secret = await s.get(CampaignSecret, cid)
            assert secret is not None
            secret.plot = {
                "fronts": [{"id": f"front_{i}", "goal": "Осада", "period": 3600, "clock_at": 0} for i in range(30)],
                "antagonists": [{"id": f"ant_{i}", "goal": "Захватить город", "threat": []} for i in range(30)],
            }

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
            assert policy.target_input_tokens == 6000

            query_log: list[str] = []

            def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
                normalized = " ".join(statement.lower().split())
                if " from events " in normalized or " from messages " in normalized:
                    query_log.append(normalized)

            event.listen(engine.sync_engine, "before_cursor_execute", capture_sql)
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
                    [EvidenceRef(campaign_id=cid, kind="event", source_id=f"ev_target_{i}") for i in range(30)]
                    + [EvidenceRef(campaign_id=cid, kind="message", source_id=f"msg_target_{i}") for i in range(30)]
                    + [EvidenceRef(campaign_id=other_cid, kind="event", source_id="ev_foreign_0")]
                ),
                mutable_subject_refs=tuple(f"creature.guard_{i}" for i in range(120)),
            )

            snapshot = await load_snapshot(ctx, req, policy=policy)
            event.remove(engine.sync_engine, "before_cursor_execute", capture_sql)

            # Assert strict context caps: 50 grounds and 80 records across
            # facts, actors, and fronts, rather than 80 facts plus everything else.
            assert len(snapshot.evidence) == policy.max_snapshot_grounds
            assert len(snapshot.facts) <= policy.max_snapshot_records  # <= 80
            assert len(snapshot.facts) + len(snapshot.actors) + len(snapshot.fronts) <= policy.max_snapshot_records
            assert len(snapshot.threads) <= policy.max_snapshot_threads  # <= 20
            assert len(snapshot.read_set) == (
                len(snapshot.facts) + len(snapshot.actors) + len(snapshot.fronts) + len(snapshot.threads)
            )
            assert len([q for q in query_log if " from events " in q]) == 1
            assert len([q for q in query_log if " from messages " in q]) == 1
            assert all("campaign_id" in q and " in " in q for q in query_log)

            event_stmt = select(Event.id).where(
                Event.campaign_id == cid,
                Event.id.in_(("ev_target_0", "ev_target_1")),
            )
            message_stmt = select(Message.id).where(
                Message.campaign_id == cid,
                Message.id.in_(("msg_target_0", "msg_target_1")),
            )
            for statement in (event_stmt, message_stmt):
                compiled = statement.compile(
                    dialect=engine.sync_engine.dialect,
                    compile_kwargs={"literal_binds": True},
                )
                if engine.dialect.name == "postgresql":
                    import json

                    raw_plan = await s.scalar(text(f"EXPLAIN (FORMAT JSON) {compiled}"))
                    plans = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan

                    def index_used(node):
                        return "Index" in node.get("Node Type", "") or any(index_used(p) for p in node.get("Plans", []))

                    assert index_used(plans[0]["Plan"]), plans
                else:
                    plan_rows = (await s.execute(text(f"EXPLAIN QUERY PLAN {compiled}"))).all()
                    plan_text = " ".join(str(row[-1]).upper() for row in plan_rows)
                    assert "USING" in plan_text or "SEARCH" in plan_text

            # Noise rows from other campaigns are not leaked.
            assert all(f.ref.campaign_id == cid for f in snapshot.facts)
            assert all(t.id.startswith("th_") for t in snapshot.threads)

    asyncio.run(_run())
