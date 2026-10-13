"""Tests for idempotent adaptation replays, receipts, and concurrency guards (Task 9)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from app.core.narrative.contracts import (
    AdaptationResult,
    EvidenceRecord,
    EvidenceRef,
    Ground,
    NarrativeSource,
)
from app.db.models import Campaign, Event, Message
from app.db.session import make_sessionmaker
from app.tools.narrative.executor import apply_in_context, narrative_key
from app.tools.runtime import open_context
from tests.game import import_base, party, run
from tests.narrative_helpers import op, policy, proposal, snapshot, thread
from tests.test_tools import play


def _make_prop(cid: str, hero_id: str, world_rev: int, src: NarrativeSource, operations=(), **overrides):
    ev = EvidenceRef(campaign_id=cid, kind="message", source_id="msg-1")
    ev_rec = EvidenceRecord(ref=ev, status="applied", audience=("party",))
    g = Ground(kind="divergence", evidence_refs=(ev,), subject_refs=(hero_id,), confidence="explicit")
    actors = overrides.pop("actors", (hero_id,))
    snap = snapshot(
        source=src,
        actors=actors,
        evidence=(ev_rec,),
        base=snapshot().base.model_copy(update={"world_revision": world_rev}),
    )
    return proposal(snap, grounds=(g,), operations=operations, **overrides)


def replay_scenario(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    src = NarrativeSource(
        campaign_id=cid,
        scope="future",
        source_kind="work",
        source_id="work-replay-test",
        stable_part=0,
    )

    first_result: AdaptationResult | None = None
    repeated_result: AdaptationResult | None = None

    async def first_turn(ctx):
        nonlocal first_result
        msg = Message(id="msg-1", campaign_id=cid, seq=9999, kind="speech", content="Сообщение игрока")
        ctx.session.add(msg)
        await ctx.session.flush()
        prop = _make_prop(
            cid,
            hero["id"],
            ctx.world.revision,
            src,
            operations=(
                op("develop_actor_role", entity_id=hero["id"], new_role="scout"),
                op("upsert_thread", thread=thread(id="th-replay-1")),
            ),
        )
        first_result = await apply_in_context(ctx, prop, policy=policy())

    play(settings, cid, [], first_turn)

    async def second_turn(ctx):
        nonlocal repeated_result
        # A different proposal with different operations, but exact same source
        prop2 = _make_prop(
            cid,
            hero["id"],
            ctx.world.revision,
            src,
            summary="Completely different author proposal",
            operations=(op("develop_actor_role", entity_id=hero["id"], new_role="blacksmith"),),
        )
        repeated_result = await apply_in_context(ctx, prop2, policy=policy())

    play(settings, cid, [], second_turn)

    receipt_count = 0

    async def count_receipts(ctx):
        nonlocal receipt_count
        key = narrative_key(src)
        stmt = (
            select(func.count())
            .select_from(Event)
            .where(
                Event.campaign_id == cid,
                Event.idempotency_key == key,
                Event.tool == "adapt_story",
            )
        )
        receipt_count = await ctx.session.scalar(stmt) or 0

    play(settings, cid, [], count_receipts)

    return first_result, repeated_result, receipt_count


def test_changed_retry_returns_original_result(settings, client, admin):
    first, repeated, receipts = replay_scenario(settings, client, admin)
    assert first.status == "applied"
    assert repeated.status == "repeated"
    assert repeated.created_ids == first.created_ids
    assert receipts == 1


def test_no_change_retry_returns_original_receipt(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    src = NarrativeSource(
        campaign_id=cid,
        scope="future",
        source_kind="work",
        source_id="work-nochange-replay",
        stable_part=0,
    )

    first_result = None
    repeated_result = None

    async def first_turn(ctx):
        nonlocal first_result
        msg = Message(id="msg-1", campaign_id=cid, seq=9999, kind="speech", content="Сообщение игрока")
        ctx.session.add(msg)
        await ctx.session.flush()
        prop = _make_prop(cid, hero["id"], ctx.world.revision, src, operations=())
        first_result = await apply_in_context(ctx, prop, policy=policy())

    play(settings, cid, [], first_turn)

    async def second_turn(ctx):
        nonlocal repeated_result
        prop2 = _make_prop(
            cid,
            hero["id"],
            ctx.world.revision,
            src,
            summary="Changed proposal after no_change",
            operations=(op("develop_actor_role", entity_id=hero["id"], new_role="guide"),),
        )
        repeated_result = await apply_in_context(ctx, prop2, policy=policy())

    play(settings, cid, [], second_turn)

    assert first_result.status == "no_change"
    assert repeated_result.status == "repeated"


def test_concurrent_two_sessions_race(settings, client, admin):
    if not settings.database_url.startswith("postgresql"):
        pytest.skip("real concurrent row-lock test requires PostgreSQL")

    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    from app.rules.dice import Dice

    maker = make_sessionmaker(client.app.state.engine)

    async def seed_evidence(session):
        from app.db.narrative import ensure_state

        session.add(Message(id="msg-1", campaign_id=cid, seq=9999, kind="speech", content="Выбираю новый путь"))
        await ensure_state(session, cid)
        await session.commit()

    run(settings, seed_evidence)
    barrier = asyncio.Barrier(2)
    results = []

    async def scenario():
        async def worker(worker_id: int):
            async with maker() as session:
                campaign = await session.get(Campaign, cid)
                ctx = await open_context(session, campaign, Dice(), turn_id=None, seat_id=None)

                src = NarrativeSource(
                    campaign_id=cid,
                    scope="future",
                    source_kind="work",
                    source_id=f"work-race-{worker_id}",
                    stable_part=0,
                )
                prop = _make_prop(
                    cid,
                    hero["id"],
                    ctx.world.revision,
                    src,
                    operations=(op("develop_actor_role", entity_id=hero["id"], new_role=f"role-{worker_id}"),),
                )

                # Wait for both workers to prepare their proposals with identical base world revision
                await barrier.wait()

                res = await apply_in_context(ctx, prop, policy=policy())
                await session.commit()
                results.append(res)

        await asyncio.gather(worker(1), worker(2))

    asyncio.run(scenario())

    statuses = [r.status for r in results]
    assert sorted(statuses) == ["applied", "stale"]
