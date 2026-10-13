"""Tests for narrative executor, receipts, and context applier (Task 9)."""

from __future__ import annotations

from sqlalchemy import select

from app.core.narrative.contracts import (
    EvidenceRecord,
    EvidenceRef,
    Ground,
    NarrativeSource,
    SnapshotRef,
)
from app.core.narrative.ports import NarrativeApplier
from app.db.models import Entity, Message, NarrativeState
from app.db.session import make_sessionmaker
from app.tools.narrative.executor import (
    ContextNarrativeApplier,
    DbNarrativeApplier,
    apply_in_context,
    find_receipt,
    narrative_key,
    write_fact_snapshots,
)
from tests.game import import_base, party
from tests.narrative_helpers import (
    fact,
    op,
    policy,
    proposal,
    snapshot,
    thread,
)
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


def test_narrative_key_is_sha256():
    src = NarrativeSource(
        campaign_id="camp-test",
        scope="scene",
        source_kind="turn",
        source_id="turn-123",
        stable_part=0,
    )
    k = narrative_key(src)
    assert isinstance(k, str)
    assert len(k) == 64
    assert k == narrative_key(src)


def test_write_fact_snapshots(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    async def scenario(ctx):
        f = fact()
        snap_ref = await write_fact_snapshots(ctx, (f,))
        assert isinstance(snap_ref, SnapshotRef)
        assert snap_ref.kind == "event"
        assert snap_ref.source_id.startswith("ev_")
        assert snap_ref.typed_address == f"event:{snap_ref.source_id}"

        ev = next((e for e in ctx.events if e.id == snap_ref.source_id), None)
        assert ev is not None
        assert ev.hidden is True
        assert ev.tool == "narrative_fact_snapshot"
        assert len(ev.payload.get("facts", [])) == 1

    play(settings, cid, [], scenario)


def test_apply_in_context_success(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    async def scenario(ctx):
        msg = Message(id="msg-1", campaign_id=cid, seq=9999, kind="speech", content="Игрок действует")
        ctx.session.add(msg)
        await ctx.session.flush()

        src = NarrativeSource(
            campaign_id=cid,
            scope="future",
            source_kind="work",
            source_id="work-42",
            stable_part=0,
        )
        t = thread(id="th-guide-route")
        f = fact(ref=fact().ref.model_copy(update={"campaign_id": cid}))
        prop = _make_prop(
            cid,
            hero["id"],
            ctx.world.revision,
            src,
            operations=(
                op("add_campaign_fact", fact=f),
                op("develop_actor_role", entity_id=hero["id"], new_role="guide"),
                op("upsert_thread", thread=t),
            ),
        )

        res = await apply_in_context(ctx, prop, policy=policy())
        assert res.status == "applied"
        assert res.reason_code == "ok"
        assert len(res.event_ids) >= 2
        assert res.budgets_used.get("novelty", 0) > 0
        assert res.budgets_used.get("operations", 0) == 3
        assert res.versions is not None

        # Verify receipt exists
        receipt = await find_receipt(ctx.session, src)
        assert receipt is not None
        assert receipt.tool == "adapt_story"
        assert receipt.hidden is True
        assert receipt.payload["adaptation"]["status"] == "applied"

        # Verify state was updated
        st = await ctx.session.scalar(select(NarrativeState).where(NarrativeState.campaign_id == cid))
        assert st is not None
        assert st.budget_counters.get("novelty_session", 0) > 0

    play(settings, cid, [], scenario)


def test_apply_in_context_no_change(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    async def scenario(ctx):
        msg = Message(id="msg-1", campaign_id=cid, seq=9999, kind="speech", content="Игрок действует")
        ctx.session.add(msg)
        await ctx.session.flush()

        src = NarrativeSource(
            campaign_id=cid,
            scope="future",
            source_kind="work",
            source_id="work-nochange",
            stable_part=0,
        )
        prop = _make_prop(cid, hero["id"], ctx.world.revision, src, operations=())

        res = await apply_in_context(ctx, prop, policy=policy())
        assert res.status == "no_change"
        assert res.reason_code == "no_change"

        receipt = await find_receipt(ctx.session, src)
        assert receipt is not None
        assert receipt.payload["adaptation"]["status"] == "no_change"

    play(settings, cid, [], scenario)


def test_apply_in_context_stale_world_revision(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    async def scenario(ctx):
        src = NarrativeSource(
            campaign_id=cid,
            scope="future",
            source_kind="work",
            source_id="work-stale",
            stable_part=0,
        )
        prop = _make_prop(
            cid,
            hero["id"],
            ctx.world.revision + 10,
            src,
            operations=(op("develop_actor_role", entity_id=hero["id"], new_role="scout"),),
        )

        res = await apply_in_context(ctx, prop, policy=policy())
        assert res.status == "stale"
        assert res.reason_code == "stale_read_set"

    play(settings, cid, [], scenario)


def test_apply_in_context_deferred_on_combat(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    async def scenario(ctx):
        ctx.world.scene.mode = "combat"
        src = NarrativeSource(
            campaign_id=cid,
            scope="scene",
            source_kind="turn",
            source_id="turn-fight",
            stable_part=0,
        )
        prop = _make_prop(
            cid,
            hero["id"],
            ctx.world.revision,
            src,
            operations=(op("develop_actor_role", entity_id=hero["id"], new_role="warrior"),),
        )

        res = await apply_in_context(ctx, prop, policy=policy())
        assert res.status == "deferred"
        assert res.reason_code == "combat_scope_locked"

    play(settings, cid, [], scenario)


def test_apply_in_context_denied_strict_mode(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    async def scenario(ctx):
        src = NarrativeSource(
            campaign_id=cid,
            scope="future",
            source_kind="work",
            source_id="work-strict",
            stable_part=0,
        )
        prop = _make_prop(cid, hero["id"], ctx.world.revision, src, operations=())

        res = await apply_in_context(ctx, prop, policy=policy(mode="strict"))
        assert res.status == "denied"
        assert res.reason_code == "policy_strict_mode"

    play(settings, cid, [], scenario)


def test_apply_in_context_denied_nonlocal_actor(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    async def scenario(ctx):
        distant_ent = Entity(
            campaign_id=cid,
            name="Distant Hermit",
            kind="creature",
            location_id="distant_cave",
            state={},
        )
        msg = Message(id="msg-1", campaign_id=cid, seq=9999, kind="speech", content="Игрок действует")
        ctx.session.add(msg)
        ctx.session.add(distant_ent)
        await ctx.session.flush()
        ctx.world.entities[distant_ent.id] = distant_ent

        src = NarrativeSource(
            campaign_id=cid,
            scope="scene",
            source_kind="turn",
            source_id="turn-nonlocal",
            stable_part=0,
        )
        prop = _make_prop(
            cid,
            hero["id"],
            ctx.world.revision,
            src,
            actors=(hero["id"], distant_ent.id),
            operations=(op("develop_actor_role", entity_id=distant_ent.id, new_role="informant"),),
        )

        res = await apply_in_context(ctx, prop, policy=policy())
        assert res.status == "denied"
        assert res.reason_code == "nonlocal_effect_denied"

    play(settings, cid, [], scenario)


def test_narrative_applier_protocol(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    async def scenario(ctx):
        pol = policy()
        context_applier = ContextNarrativeApplier(ctx, policy=pol)
        assert isinstance(context_applier, NarrativeApplier)

        maker = make_sessionmaker(ctx.session.bind)
        db_applier = DbNarrativeApplier(maker, policy_provider=lambda: pol)
        assert isinstance(db_applier, NarrativeApplier)

    play(settings, cid, [], scenario)
