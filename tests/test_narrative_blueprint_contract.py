"""Tests for spatial blueprint commitments and selective fact freezing (Task 18)."""

import asyncio

from app.core.narrative.contracts import (
    FactRef,
    Ground,
    SnapshotRef,
)
from app.core.narrative.facts import revise_draft
from app.db.models import Campaign, NarrativeFact
from app.db.session import make_sessionmaker
from app.rules.dice import Dice
from app.tools.narrative.commitments import record_commitments
from app.tools.runtime import open_context
from tests.game import import_base, party


def blueprint_commitment_scenario(settings, client, admin) -> dict:
    """End-to-end scenario: spatial producer commits passage fact without freezing unrelated NPC motive."""
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    snap_passage = SnapshotRef(kind="package", source_id="p1", typed_address="module:loc.passage:secret_truth")
    passage_ref = FactRef(
        campaign_id=cid,
        namespace="module",
        subject_id="loc.passage",
        key="secret_truth",
        version=1,
        snapshot_ref=snap_passage,
    )

    snap_npc = SnapshotRef(kind="package", source_id="p1", typed_address="module:npc.guide:motivation")

    async def _run():
        # 1. Insert two draft facts
        async with maker() as s:
            f_passage = NarrativeFact(
                campaign_id=cid,
                namespace="module",
                subject_id="loc.passage",
                key="secret_truth",
                version=1,
                kind="truth",
                temporal_semantics="current_state",
                freedom="draft",
                value="Потайной лаз за гобеленом",
                audience=[],
                depends_on=[],
                source_refs=[],
                snapshot_ref=snap_passage.model_dump(),
            )
            f_npc = NarrativeFact(
                campaign_id=cid,
                namespace="module",
                subject_id="npc.guide",
                key="motivation",
                version=1,
                kind="intent",
                temporal_semantics="current_state",
                freedom="draft",
                value="Провести отряд к реке",
                audience=[],
                depends_on=[],
                source_refs=[],
                snapshot_ref=snap_npc.model_dump(),
            )
            s.add(f_passage)
            s.add(f_npc)
            await s.commit()

        # 2. Spatial producer records commitments only for passage fact
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            sealed = await record_commitments(
                ctx,
                (passage_ref,),
                reason="spatial_blueprint_materialized",
                snapshot_ref=snap_passage,
            )
            assert passage_ref in sealed
            await s.commit()

        # 3. Check freedoms and test revision
        async with maker() as s:
            from sqlalchemy import select

            p_row = (
                await s.execute(
                    select(NarrativeFact).where(
                        NarrativeFact.campaign_id == cid,
                        NarrativeFact.subject_id == "loc.passage",
                        NarrativeFact.key == "secret_truth",
                    )
                )
            ).scalar_one()

            n_row = (
                await s.execute(
                    select(NarrativeFact).where(
                        NarrativeFact.campaign_id == cid,
                        NarrativeFact.subject_id == "npc.guide",
                        NarrativeFact.key == "motivation",
                    )
                )
            ).scalar_one()

            passage_fact_state = p_row.as_state() if hasattr(p_row, "as_state") else None
            if passage_fact_state is None:
                from app.core.narrative.contracts import FactState

                passage_fact_state = FactState(
                    ref=passage_ref,
                    kind=p_row.kind,
                    temporal_semantics=p_row.temporal_semantics,
                    freedom=p_row.freedom,
                    value=p_row.value,
                    audience=tuple(p_row.audience or ()),
                    depends_on=(),
                )

            # Late revision on committed passage is denied
            div_ground = Ground(kind="divergence", evidence_refs=())
            rev_result = revise_draft(passage_fact_state, "Другой потайной ход", div_ground, ())
            late_denied = "fact_committed" in rev_result.violations

            return {
                "hidden_passage_freedom": p_row.freedom,
                "unused_npc_motive_freedom": n_row.freedom,
                "late_passage_revision_denied": late_denied,
            }

    return asyncio.run(_run())


def test_blueprint_does_not_freeze_unrelated_npc_motive(settings, client, admin):
    """Spatial blueprint commitments freeze materialized passages while leaving unrelated NPC motives as drafts."""
    report = blueprint_commitment_scenario(settings, client, admin)
    assert report["hidden_passage_freedom"] == "committed"
    assert report["unused_npc_motive_freedom"] == "draft"
    assert report["late_passage_revision_denied"]
