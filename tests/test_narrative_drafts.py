"""Tests for draft fact revision rules and concurrency guards (Task 17)."""

import asyncio
from typing import Any

from app.core.narrative.contracts import (
    FactRef,
    Ground,
    SnapshotRef,
)
from app.core.narrative.facts import revise_draft
from tests.narrative_helpers import fact


def divergence_ground(**overrides: Any) -> Ground:
    """Factory for divergence Ground for test scenarios."""
    defaults: dict[str, Any] = {
        "kind": "divergence",
        "evidence_refs": (),
        "confidence": "explicit",
    }
    defaults.update(overrides)
    return Ground(**defaults)


def test_unrevealed_materialized_secret_cannot_be_rewritten():
    """Committed facts cannot be rewritten as drafts."""
    old = fact(freedom="committed", audience=())
    result = revise_draft(old, "другая истина", divergence_ground(), ())
    assert result.violations == ("fact_committed",)
    assert result.after is None


def test_draft_fact_can_be_revised_successfully():
    """Draft fact updates value and increments version when revision succeeds."""
    old = fact(freedom="draft", value="первоначальный план")
    result = revise_draft(old, "новый тайный план", divergence_ground(), ())
    assert result.violations == ()
    assert result.after is not None
    assert result.after.value == "новый тайный план"
    assert result.after.ref.version == old.ref.version + 1
    assert result.after.freedom == "draft"


def test_historical_fact_cannot_be_rewritten():
    """Historical committed narrative facts cannot be altered by draft revision."""
    old = fact(freedom="committed", temporal_semantics="historical")
    result = revise_draft(old, "другое прошлое", divergence_ground(), ())
    assert "fact_committed" in result.violations or "historical_fact_immutable" in result.violations
    assert result.after is None


def test_historical_draft_can_be_revised_before_commitment():
    """Historical draft can be revised before it is committed."""
    old = fact(freedom="draft", temporal_semantics="historical", value="старый черновик истории")
    result = revise_draft(old, "уточнённая история", divergence_ground(), ())
    assert result.violations == ()
    assert result.after is not None
    assert result.after.value == "уточнённая история"
    assert result.after.freedom == "draft"


def test_invalid_ground_rejects_draft_revision():
    """Draft revision requires consequence, relationship, or divergence ground."""
    old = fact(freedom="draft")
    bad_ground = Ground(kind="world_time", evidence_refs=())
    result = revise_draft(old, "новое", bad_ground, ())
    assert "invalid_ground_for_draft_revision" in result.violations
    assert result.after is None


def test_revise_draft_fact_in_context(settings, client, admin):
    """End-to-end: ReviseDraftFactOp updates draft fact in active database context."""
    from app.core.narrative.contracts import (
        AdaptationProposal,
        EvidenceRef,
        NarrativePolicy,
        ReviseDraftFactOp,
        VersionSet,
    )
    from app.db.models import Campaign, NarrativeFact
    from app.db.session import make_sessionmaker
    from app.rules.dice import Dice
    from app.tools.narrative.executor import apply_in_context
    from app.tools.runtime import open_context
    from tests.game import import_base, party

    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        snap_ref = SnapshotRef(kind="package", source_id="p1", typed_address="module:npc.scout:motivation")
        f_ref = FactRef(
            campaign_id=cid,
            namespace="module",
            subject_id="npc.scout",
            key="motivation",
            version=1,
            snapshot_ref=snap_ref,
        )

        # 1. Insert draft fact
        async with maker() as s:
            f = NarrativeFact(
                campaign_id=cid,
                namespace="module",
                subject_id="npc.scout",
                key="motivation",
                version=1,
                kind="intent",
                temporal_semantics="current_state",
                freedom="draft",
                value="Спасти деревню",
                audience=["party"],
                depends_on=[],
                source_refs=[],
                snapshot_ref={"kind": "package", "source_id": "p1", "typed_address": "module:npc.scout:motivation"},
            )
            s.add(f)
            from app.db.narrative import ensure_state

            st = await ensure_state(s, cid)
            st.mode = "adaptive"
            await s.commit()

        # 2. Revise via proposal in context
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            from app.tools.narrative.sources import bind_scene_sources

            slots = await bind_scene_sources(ctx)
            src = slots[0]

            ev = await ctx.record("evidence", payload={"result": "scout_agreed", "subject_refs": ["npc.scout"]})

            prop = AdaptationProposal(
                schema_version=1,
                proposal_id="prop_revise_1",
                source=src,
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
                        subject_refs=("npc.scout",),
                    ),
                ),
                summary="Разведчик меняет мотив",
                operations=(
                    ReviseDraftFactOp(
                        target_ref=f_ref,
                        new_value="Увести жителей в горы",
                    ),
                ),
            )
            policy = NarrativePolicy(mode="adaptive")
            res = await apply_in_context(ctx, prop, policy=policy)
            assert res.status == "applied"
            await s.commit()

        # 3. Verify in database
        async with maker() as s:
            from sqlalchemy import select

            fact_row = (
                await s.execute(
                    select(NarrativeFact).where(
                        NarrativeFact.campaign_id == cid,
                        NarrativeFact.subject_id == "npc.scout",
                        NarrativeFact.key == "motivation",
                    )
                )
            ).scalar_one()
            assert fact_row.value == "Увести жителей в горы"
            assert fact_row.version == 2
            assert fact_row.freedom == "draft"

    asyncio.run(_run())


def test_revise_committed_fact_in_context_denied(settings, client, admin):
    """Attempting to revise a committed fact in context is denied by policy."""
    from app.core.narrative.contracts import (
        AdaptationProposal,
        EvidenceRef,
        NarrativePolicy,
        ReviseDraftFactOp,
        VersionSet,
    )
    from app.db.models import Campaign, NarrativeFact
    from app.db.session import make_sessionmaker
    from app.rules.dice import Dice
    from app.tools.narrative.executor import apply_in_context
    from app.tools.runtime import open_context
    from tests.game import import_base, party

    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        snap_ref = SnapshotRef(kind="package", source_id="p1", typed_address="module:npc.boss:role")
        f_ref = FactRef(
            campaign_id=cid,
            namespace="module",
            subject_id="npc.boss",
            key="role",
            version=1,
            snapshot_ref=snap_ref,
        )

        async with maker() as s:
            f = NarrativeFact(
                campaign_id=cid,
                namespace="module",
                subject_id="npc.boss",
                key="role",
                version=1,
                kind="truth",
                temporal_semantics="current_state",
                freedom="committed",  # already committed!
                value="Глава стражи",
                audience=["party"],
                depends_on=[],
                source_refs=[],
                snapshot_ref={"kind": "package", "source_id": "p1", "typed_address": "module:npc.boss:role"},
            )
            s.add(f)
            from app.db.narrative import ensure_state

            st = await ensure_state(s, cid)
            st.mode = "adaptive"
            await s.commit()

        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            from app.tools.narrative.sources import bind_scene_sources

            slots = await bind_scene_sources(ctx)
            src = slots[0]

            ev = await ctx.record("evidence", payload={"result": "boss_seen"})

            prop = AdaptationProposal(
                schema_version=1,
                proposal_id="prop_revise_fail",
                source=src,
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
                    ),
                ),
                summary="Попытка переписать закреплённую роль",
                operations=(
                    ReviseDraftFactOp(
                        target_ref=f_ref,
                        new_value="Предатель",
                    ),
                ),
            )
            policy = NarrativePolicy(mode="adaptive")
            res = await apply_in_context(ctx, prop, policy=policy)
            assert res.status == "denied"
            assert res.reason_code == "fact_committed"

    asyncio.run(_run())


def test_add_cannot_replace_committed_history(settings, client, admin):
    """Adding a fact cannot overwrite or demote an existing committed historical fact."""
    from sqlalchemy import select

    from app.core.narrative.contracts import (
        AdaptationProposal,
        AddCampaignFactOp,
        EvidenceRef,
        FactRef,
        FactState,
        Ground,
        NarrativePolicy,
        SnapshotRef,
        VersionSet,
    )
    from app.db.models import Campaign, NarrativeFact
    from app.db.narrative import ensure_state
    from app.db.session import make_sessionmaker
    from app.rules.dice import Dice
    from app.tools.narrative.executor import apply_in_context
    from app.tools.narrative.sources import bind_scene_sources
    from app.tools.runtime import open_context
    from tests.game import import_base, party

    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        f_ref = FactRef(
            campaign_id=cid,
            namespace="campaign",
            subject_id="duke",
            key="secret_truth",
            version=1,
            snapshot_ref=SnapshotRef(kind="event", source_id="ev-1", typed_address="campaign:duke:status"),
        )
        # 1. Insert committed historical fact: «герцог умер»
        async with maker() as s:
            f = NarrativeFact(
                campaign_id=cid,
                namespace="campaign",
                subject_id="duke",
                key="secret_truth",
                version=1,
                kind="truth",
                temporal_semantics="historical",
                freedom="committed",
                value="герцог умер",
                audience=["party"],
                depends_on=[],
                source_refs=[],
                snapshot_ref={"kind": "event", "source_id": "ev-1", "typed_address": "campaign:duke:status"},
            )
            s.add(f)
            st = await ensure_state(s, cid)
            st.mode = "adaptive"
            await s.commit()

        # 2. Attempt to add fact at same address: «не умирал», draft
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            slots = await bind_scene_sources(ctx)
            src = slots[0]
            ev = await ctx.record("evidence", payload={"result": "rumor_heard"})

            new_fact = FactState(
                ref=f_ref,
                kind="truth",
                temporal_semantics="historical",
                freedom="draft",
                value="не умирал",
                audience=("party",),
                depends_on=(),
            )
            prop = AdaptationProposal(
                schema_version=1,
                proposal_id="prop_overwrite_fail",
                source=src,
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
                        subject_refs=("duke",),
                    ),
                ),
                summary="Попытка переписать смерть герцога",
                operations=(AddCampaignFactOp(fact=new_fact),),
            )
            res = await apply_in_context(ctx, prop, policy=NarrativePolicy(mode="adaptive"))
            assert res.status == "denied"
            assert res.reason_code in ("historical_fact_immutable", "cannot_demote_committed_fact")

        # 3. Verify fact in DB is unchanged: still committed, still «герцог умер», version 1
        async with maker() as s:
            row = (
                await s.execute(
                    select(NarrativeFact).where(
                        NarrativeFact.campaign_id == cid,
                        NarrativeFact.namespace == "campaign",
                        NarrativeFact.subject_id == "duke",
                        NarrativeFact.key == "secret_truth",
                    )
                )
            ).scalar_one()
            assert row.freedom == "committed"
            assert row.value == "герцог умер"
            assert row.version == 1

    asyncio.run(_run())


def test_cannot_change_fact_semantics(settings, client, admin):
    """Attempt to alter fact kind or temporal_semantics is rejected."""
    from app.core.narrative.contracts import (
        AdaptationProposal,
        AddCampaignFactOp,
        EvidenceRef,
        FactRef,
        FactState,
        Ground,
        NarrativePolicy,
        SnapshotRef,
        VersionSet,
    )
    from app.db.models import Campaign, NarrativeFact
    from app.db.narrative import ensure_state
    from app.db.session import make_sessionmaker
    from app.rules.dice import Dice
    from app.tools.narrative.executor import apply_in_context
    from app.tools.narrative.sources import bind_scene_sources
    from app.tools.runtime import open_context
    from tests.game import import_base, party

    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        f_ref = FactRef(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc.scout",
            key="motivation",
            version=1,
            snapshot_ref=SnapshotRef(kind="event", source_id="ev-1", typed_address="campaign:npc.scout:motivation"),
        )
        async with maker() as s:
            f = NarrativeFact(
                campaign_id=cid,
                namespace="campaign",
                subject_id="npc.scout",
                key="motivation",
                version=1,
                kind="intent",
                temporal_semantics="current_state",
                freedom="draft",
                value="Спасти деревню",
                audience=["party"],
                depends_on=[],
                source_refs=[],
                snapshot_ref={"kind": "event", "source_id": "ev-1", "typed_address": "campaign:npc.scout:motivation"},
            )
            s.add(f)
            st = await ensure_state(s, cid)
            st.mode = "adaptive"
            await s.commit()

        # Attempt to change temporal_semantics from current_state to historical
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            slots = await bind_scene_sources(ctx)
            src = slots[0]
            ev = await ctx.record("evidence", payload={"result": "talked"})

            new_fact = FactState(
                ref=f_ref,
                kind="intent",
                temporal_semantics="historical",  # changed!
                freedom="draft",
                value="Спасти деревню",
                audience=("party",),
                depends_on=(),
            )
            prop = AdaptationProposal(
                schema_version=1,
                proposal_id="prop_semantics_fail",
                source=src,
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
                        subject_refs=("npc.scout",),
                    ),
                ),
                summary="Попытка подменить семантику факта",
                operations=(AddCampaignFactOp(fact=new_fact),),
            )
            res = await apply_in_context(ctx, prop, policy=NarrativePolicy(mode="adaptive"))
            assert res.status == "denied"
            assert res.reason_code == "cannot_change_fact_semantics"

    asyncio.run(_run())


def test_fact_update_event_has_inverse(settings, client, admin):
    """Updating a fact records before/after and inverse rollback payload in event."""
    from sqlalchemy import select

    from app.core.narrative.contracts import (
        AdaptationProposal,
        EvidenceRef,
        FactRef,
        Ground,
        NarrativePolicy,
        ReviseDraftFactOp,
        SnapshotRef,
        VersionSet,
    )
    from app.db.models import Campaign, Event, NarrativeFact
    from app.db.narrative import ensure_state
    from app.db.session import make_sessionmaker
    from app.rules.dice import Dice
    from app.tools.narrative.executor import apply_in_context
    from app.tools.narrative.sources import bind_scene_sources
    from app.tools.runtime import open_context
    from tests.game import import_base, party

    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        f_ref = FactRef(
            campaign_id=cid,
            namespace="module",
            subject_id="npc.scout",
            key="motivation",
            version=1,
            snapshot_ref=SnapshotRef(kind="package", source_id="p1", typed_address="module:npc.scout:motivation"),
        )
        async with maker() as s:
            f = NarrativeFact(
                campaign_id=cid,
                namespace="module",
                subject_id="npc.scout",
                key="motivation",
                version=1,
                kind="intent",
                temporal_semantics="current_state",
                freedom="draft",
                value="Старое значение",
                audience=["party"],
                depends_on=[],
                source_refs=[],
                snapshot_ref={"kind": "package", "source_id": "p1", "typed_address": "module:npc.scout:motivation"},
            )
            s.add(f)
            st = await ensure_state(s, cid)
            st.mode = "adaptive"
            await s.commit()

        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            slots = await bind_scene_sources(ctx)
            src = slots[0]
            ev = await ctx.record("evidence", payload={"result": "new_decision"})

            prop = AdaptationProposal(
                schema_version=1,
                proposal_id="prop_revise_inv",
                source=src,
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
                        subject_refs=("npc.scout",),
                    ),
                ),
                summary="Смена мотивации разведчика",
                operations=(ReviseDraftFactOp(target_ref=f_ref, new_value="Новое значение"),),
            )
            res = await apply_in_context(ctx, prop, policy=NarrativePolicy(mode="adaptive"))
            assert res.status == "applied"

            # Verify apply_narrative_fact event contains before, after, inverse
            ev_row = (
                await s.execute(
                    select(Event).where(
                        Event.campaign_id == cid,
                        Event.tool == "apply_narrative_fact",
                    )
                )
            ).scalar_one()
            payload = ev_row.payload or {}
            assert payload.get("before") == "Старое значение"
            assert payload.get("after") == "Новое значение"
            assert payload.get("inverse") is not None
            assert payload["inverse"].get("value") == "Старое значение"

    asyncio.run(_run())
