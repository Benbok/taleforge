"""Tests for scoped novelty budgets: scene boundaries, session budget refs, and slot reuse."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.narrative.contracts import (
    AdaptationProposal,
    AddCampaignFactOp,
    EvidenceRef,
    FactRef,
    FactState,
    Ground,
    IntroduceActorOp,
    NarrativePolicy,
    SnapshotRef,
    SnapshotRequest,
    VersionSet,
)
from app.db.models import Campaign, NarrativeState
from app.db.session import make_sessionmaker
from app.rules.dice import Dice
from app.tools.narrative.context import load_snapshot
from app.tools.narrative.executor import apply_in_context
from app.tools.narrative.sources import bind_scene_sources
from app.tools.runtime import open_context
from tests.game import import_base, party


def test_future_preparation_does_not_consume_current_scene_budget(settings, client, admin):
    """Future scope proposal consumes session novelty, but does not consume current scene limit."""
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            slots = await bind_scene_sources(ctx)
            # slot 2 is future scope
            src_future = [s for s in slots if s.scope == "future"][0]
            ev = await ctx.record("evidence", payload={"result": "scout_report"})

            snap_ref = SnapshotRef(kind="event", source_id=ev.id, typed_address="campaign:future:prep")
            f_ref = FactRef(
                campaign_id=cid,
                namespace="campaign",
                subject_id="future",
                key="situation_premise",
                version=1,
                snapshot_ref=snap_ref,
            )
            new_fact = FactState(
                ref=f_ref,
                kind="truth",
                temporal_semantics="current_state",
                freedom="draft",
                value="Засада на перевале готовится",
                audience=("party",),
                depends_on=(),
            )
            prop = AdaptationProposal(
                schema_version=1,
                proposal_id="prop_future_novelty",
                source=src_future,
                base=VersionSet(
                    world_revision=ctx.world.revision,
                    plan_version=1,
                    narrative_revision=1,
                    policy_version=1,
                ),
                grounds=(
                    Ground(
                        kind="divergence",
                        evidence_refs=(EvidenceRef(campaign_id=cid, kind="event", source_id=ev.id),),
                        subject_refs=("future",),
                    ),
                ),
                summary="Подготовка будущей засады",
                operations=(AddCampaignFactOp(fact=new_fact),),
            )
            res = await apply_in_context(ctx, prop, policy=NarrativePolicy(mode="adaptive"))
            assert res.status == "applied"
            assert res.budgets_used.get("novelty", 0) == 1
            await s.commit()

        # Check snapshot for current scene has intact scene budget of 3
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            slots = await bind_scene_sources(ctx)
            src_scene = slots[0]
            snap = await load_snapshot(ctx, SnapshotRequest(source=src_scene), policy=NarrativePolicy(mode="adaptive"))
            # Scene budget must still be 3 (not 2)
            assert snap.budgets.get("novelty_scene") == 3
            # Session budget must be 11 (12 - 1)
            assert snap.budgets.get("novelty_session") == 11

    asyncio.run(_run())


def test_new_scene_gets_fresh_budget_3(settings, client, admin):
    """Transitioning to a new scene boundary grants fresh scene novelty budget (3)."""
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        # 1. In scene loc_tavern, spend 3 scene novelty
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            ctx.world.scene.location_id = "loc_tavern"
            slots = await bind_scene_sources(ctx)
            src_scene = slots[0]
            ev = await ctx.record("evidence", payload={"result": "tavern_event"})

            facts = [
                FactState(
                    ref=FactRef(
                        campaign_id=cid,
                        namespace="campaign",
                        subject_id=f"tavern_fact_{i}",
                        key="situation_premise",
                        version=1,
                        snapshot_ref=SnapshotRef(
                            kind="event", source_id=ev.id, typed_address=f"campaign:tavern_fact_{i}:situation_premise"
                        ),
                    ),
                    kind="truth",
                    temporal_semantics="current_state",
                    freedom="draft",
                    value=f"Факт в таверне {i}",
                    audience=("party",),
                    depends_on=(),
                )
                for i in range(3)
            ]
            prop = AdaptationProposal(
                schema_version=1,
                proposal_id="prop_spend_scene",
                source=src_scene,
                base=VersionSet(
                    world_revision=ctx.world.revision,
                    plan_version=1,
                    narrative_revision=1,
                    policy_version=1,
                ),
                grounds=(
                    Ground(
                        kind="divergence",
                        evidence_refs=(EvidenceRef(campaign_id=cid, kind="event", source_id=ev.id),),
                        subject_refs=("tavern",),
                    ),
                ),
                summary="Тратим 3 новизны в таверне",
                operations=tuple(AddCampaignFactOp(fact=f) for f in facts),
            )
            res = await apply_in_context(ctx, prop, policy=NarrativePolicy(mode="adaptive"))
            assert res.status == "applied"
            await s.commit()

        # 2. Check scene budget in tavern is 0
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            ctx.world.scene.location_id = "loc_tavern"
            slots = await bind_scene_sources(ctx)
            snap = await load_snapshot(ctx, SnapshotRequest(source=slots[0]), policy=NarrativePolicy(mode="adaptive"))
            assert snap.budgets.get("novelty_scene") == 0

        # 3. Move party to loc_dungeon (new scene): novelty_scene must be fresh 3
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            ctx.world.scene.location_id = "loc_dungeon"
            slots = await bind_scene_sources(ctx)
            snap = await load_snapshot(ctx, SnapshotRequest(source=slots[0]), policy=NarrativePolicy(mode="adaptive"))
            assert snap.budgets.get("novelty_scene") == 3
            # But session spent is preserved: 12 - 3 = 9
            assert snap.budgets.get("novelty_session") == 9

    asyncio.run(_run())


def test_new_session_gets_fresh_budget_12(settings, client, admin):
    """A new session budget ref gets fresh session novelty budget (12)."""
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        # Setup session 1 with 12 novelty spent
        async with maker() as s:
            st = await s.scalar(select(NarrativeState).where(NarrativeState.campaign_id == cid))
            if not st:
                from app.db.narrative import ensure_state

                st = await ensure_state(s, cid)
            st.budget_counters = {
                "session_budget_ref": "sess_1",
                "novelty_session": 12,
                "session_spent": {"sess_1": 12},
            }
            await s.commit()

        # Context with game_session_id="sess_1": session budget is 0
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx1 = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            ctx1.game_session_id = "sess_1"
            slots = await bind_scene_sources(ctx1)
            snap1 = await load_snapshot(ctx1, SnapshotRequest(source=slots[0]), policy=NarrativePolicy(mode="adaptive"))
            assert snap1.budgets.get("novelty_session") == 0

        # Context with game_session_id="sess_2" (new session): session budget is 12
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx2 = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            ctx2.game_session_id = "sess_2"
            slots = await bind_scene_sources(ctx2)
            snap2 = await load_snapshot(ctx2, SnapshotRequest(source=slots[0]), policy=NarrativePolicy(mode="adaptive"))
            assert snap2.budgets.get("novelty_session") == 12

    asyncio.run(_run())


def test_retry_does_not_reset_budget_counters(settings, client, admin):
    """Replaying or retrying adaptation does not reset or double charge novelty counters."""
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id="t_stable_retry", seat_id=None)
            slots = await bind_scene_sources(ctx)
            src_scene = slots[0]
            ev = await ctx.record("evidence", payload={"result": "test_event"})

            prop = AdaptationProposal(
                schema_version=1,
                proposal_id="prop_retry_1",
                source=src_scene,
                base=VersionSet(
                    world_revision=ctx.world.revision,
                    plan_version=1,
                    narrative_revision=1,
                    policy_version=1,
                ),
                grounds=(
                    Ground(
                        kind="divergence",
                        evidence_refs=(EvidenceRef(campaign_id=cid, kind="event", source_id=ev.id),),
                        subject_refs=("npc_retry",),
                    ),
                ),
                summary="Первое применение",
                operations=(
                    AddCampaignFactOp(
                        fact=FactState(
                            ref=FactRef(
                                campaign_id=cid,
                                namespace="campaign",
                                subject_id="npc_retry",
                                key="situation_premise",
                                version=1,
                                snapshot_ref=SnapshotRef(
                                    kind="event", source_id=ev.id, typed_address="campaign:npc_retry:situation_premise"
                                ),
                            ),
                            kind="truth",
                            temporal_semantics="current_state",
                            freedom="draft",
                            value="Первое значение",
                            audience=("party",),
                            depends_on=(),
                        )
                    ),
                ),
            )
            res1 = await apply_in_context(ctx, prop, policy=NarrativePolicy(mode="adaptive"))
            assert res1.status == "applied"
            assert res1.budgets_used.get("novelty") == 1
            await s.commit()

        # Retry with same source in same turn
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx_retry = await open_context(s, camp, Dice(), turn_id="t_stable_retry", seat_id=None)
            slots = await bind_scene_sources(ctx_retry)
            res2 = await apply_in_context(ctx_retry, prop, policy=NarrativePolicy(mode="adaptive"))
            # Returns idempotently applied receipt
            assert res2.status in ("applied", "repeated")

            st = await s.scalar(select(NarrativeState).where(NarrativeState.campaign_id == cid))
            # Spent is still 1, not 2 and not 0
            scene_ref = (
                getattr(ctx_retry.world.scene, "boundary_id", None)
                or f"scene:{ctx_retry.world.scene.location_id or 'default'}"
            )
            spent_scene = (st.budget_counters.get("scene_spent") or {}).get(
                scene_ref, st.budget_counters.get("novelty_scene", 0)
            )
            assert spent_scene == 1

    asyncio.run(_run())


def test_materializing_prepared_actor_does_not_double_charge_session(settings, client, admin):
    """An actor slot introduced in future sketch does not double-charge session novelty when materialized."""
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        # 1. Prepare future actor slot (charges session novelty 1)
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            slots = await bind_scene_sources(ctx)
            src_future = [s for s in slots if s.scope == "future"][0]
            ev = await ctx.record("evidence", payload={"result": "rumor"})

            prop1 = AdaptationProposal(
                schema_version=1,
                proposal_id="prop_prep_actor",
                source=src_future,
                base=VersionSet(
                    world_revision=ctx.world.revision,
                    plan_version=1,
                    narrative_revision=1,
                    policy_version=1,
                ),
                grounds=(
                    Ground(
                        kind="relationship",
                        evidence_refs=(EvidenceRef(campaign_id=cid, kind="event", source_id=ev.id),),
                        subject_refs=("slot_guide",),
                    ),
                ),
                summary="Подготовка проводника",
                operations=(
                    IntroduceActorOp(
                        actor_slot="slot_guide",
                        template_id="creature.commoner",
                        place_ref="loc_camp",
                        attitude="friendly",
                        public_description="Старый проводник",
                        mode="sketch",
                    ),
                    AddCampaignFactOp(
                        fact=FactState(
                            ref=FactRef(
                                campaign_id=cid,
                                namespace="campaign",
                                subject_id="slot_guide",
                                key="situation_premise",
                                version=1,
                                snapshot_ref=SnapshotRef(
                                    kind="event", source_id=ev.id, typed_address="campaign:slot_guide:situation_premise"
                                ),
                            ),
                            kind="truth",
                            temporal_semantics="current_state",
                            freedom="draft",
                            value="Проводник знает тропу",
                            audience=("party",),
                            depends_on=(),
                        )
                    ),
                ),
            )
            res1 = await apply_in_context(ctx, prop1, policy=NarrativePolicy(mode="adaptive"))
            assert res1.status == "applied"
            await s.commit()

        # 2. Materialize the actor in scene: session novelty is not charged a second time
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            slots = await bind_scene_sources(ctx)
            src_scene = slots[0]
            ev2 = await ctx.record("evidence", payload={"result": "meeting"})

            prop2 = AdaptationProposal(
                schema_version=1,
                proposal_id="prop_mat_actor",
                source=src_scene,
                base=VersionSet(
                    world_revision=ctx.world.revision,
                    plan_version=1,
                    narrative_revision=res1.versions.narrative_revision if res1.versions else 1,
                    policy_version=1,
                ),
                grounds=(
                    Ground(
                        kind="relationship",
                        evidence_refs=(EvidenceRef(campaign_id=cid, kind="event", source_id=ev2.id),),
                        subject_refs=("slot_guide",),
                    ),
                ),
                summary="Материализация проводника в сцене",
                operations=(
                    IntroduceActorOp(
                        actor_slot="slot_guide",
                        template_id="creature.commoner",
                        place_ref="",
                        attitude="friendly",
                        public_description="Старый проводник выходит из тени",
                        mode="materialize",
                    ),
                ),
            )
            res2 = await apply_in_context(ctx, prop2, policy=NarrativePolicy(mode="adaptive"))
            assert res2.status == "applied"
            # Materializing existing pre-paid slot has 0 novelty cost
            assert res2.budgets_used.get("novelty", 0) == 0

    asyncio.run(_run())
