"""Tests for narrative tool boundaries and campaign isolation (F1).

Verifies:
1. Internal tools (the 6 apply_* narrative tools) are never exposed in decision_tools or tool_specs.
2. Direct execute() calls to internal tools without an InternalGrant are denied without modifying DB.
3. Nested foreign campaign references in proposals are rejected; foreign campaign is untouched.
"""

from __future__ import annotations

from sqlalchemy import select

from app.agents.master.common import DECISION_TOOLS, decision_tools
from app.core.narrative.contracts import (
    EvidenceRecord,
    EvidenceRef,
    FactRef,
    Ground,
    NarrativeSource,
    SnapshotRef,
)
from app.db.models import Event, NarrativeFact
from app.tools.narrative.executor import apply_in_context
from app.tools.registry import execute, tool_specs
from tests.game import import_base, party
from tests.narrative_helpers import fact, op, policy, proposal, snapshot
from tests.test_tools import play

INTERNAL_TOOLS = {
    "apply_narrative_fact",
    "apply_narrative_thread",
    "apply_future_situation",
    "apply_existing_front_intent",
    "apply_advance_front",
    "apply_narrative_actor_sketch",
}


def test_internal_tools_not_exposed(settings, client, admin):
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]

    # 1. Global DECISION_TOOLS must not contain internal tools
    for tool_name in INTERNAL_TOOLS:
        assert tool_name not in DECISION_TOOLS, f"{tool_name} exposed in DECISION_TOOLS"

    # 2. Context-dependent decision_tools and tool_specs must not contain internal tools
    async def scenario(ctx):
        dt = decision_tools(ctx)
        for tool_name in INTERNAL_TOOLS:
            assert tool_name not in dt, f"{tool_name} exposed in decision_tools(ctx)"

        specs = tool_specs(ctx.world)
        spec_names = {s["function"]["name"] for s in specs}
        for tool_name in INTERNAL_TOOLS:
            assert tool_name not in spec_names, f"{tool_name} exposed in tool_specs"

    play(settings, cid, [], scenario)


def test_direct_internal_call_denied(settings, client, admin):
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]

    async def scenario(ctx):
        # Direct call to internal apply_narrative_fact must be denied
        raw_args = {
            "campaign_id": cid,
            "namespace": "campaign",
            "subject_id": "creature.guard",
            "key": "secret",
            "value": "infiltrated",
            "kind": "truth",
            "temporal_semantics": "current_state",
            "freedom": "committed",
        }
        res = await execute(ctx, "apply_narrative_fact", raw_args)
        assert res["ok"] is False
        assert res.get("failure", {}).get("code") in ("internal_tool_denied", "permission_denied")

        # Verify database was not modified
        q = select(NarrativeFact).where(
            NarrativeFact.campaign_id == cid,
            NarrativeFact.namespace == "campaign",
            NarrativeFact.subject_id == "creature.guard",
            NarrativeFact.key == "secret",
        )
        fact_in_db = (await ctx.session.execute(q)).scalar_one_or_none()
        assert fact_in_db is None

    play(settings, cid, [], scenario)


def test_nested_foreign_campaign_rejected(settings, client, admin):
    import_base(settings)
    from tests.test_api import make_campaign

    c_a, _heads_a, hero_a = party(client, admin)
    c_b = make_campaign(client, admin)
    cid_a = c_a["id"]
    cid_b = c_b["id"]

    async def scenario(ctx_a):
        # Initial state of campaign B
        events_b_count = len((await ctx_a.session.scalars(select(Event).where(Event.campaign_id == cid_b))).all())
        q_facts_b = select(NarrativeFact).where(NarrativeFact.campaign_id == cid_b)
        facts_b_count = len((await ctx_a.session.scalars(q_facts_b)).all())

        src_a = NarrativeSource(
            campaign_id=cid_a,
            scope="future",
            source_kind="work",
            source_id="work-1",
            stable_part=0,
        )
        ev_a = EvidenceRef(campaign_id=cid_a, kind="message", source_id="msg-1")
        ev_rec_a = EvidenceRecord(ref=ev_a, status="applied", audience=("party",))
        g_a = Ground(kind="divergence", evidence_refs=(ev_a,), subject_refs=(hero_a["id"],), confidence="explicit")

        # Malicious fact trying to write to campaign B
        foreign_fact_ref = FactRef(
            campaign_id=cid_b,  # FOREIGN CAMPAIGN!
            namespace="campaign",
            subject_id="hero.b",
            key="motivation",
            version=1,
            snapshot_ref=SnapshotRef(kind="package", source_id="p1", typed_address="package:p1"),
        )
        foreign_fact = fact(ref=foreign_fact_ref, value="foreign injection")

        snap_a = snapshot(
            source=src_a,
            actors=(hero_a["id"],),
            evidence=(ev_rec_a,),
            base=snapshot().base.model_copy(update={"world_revision": ctx_a.world.revision}),
        )
        prop = proposal(
            snap_a,
            grounds=(g_a,),
            operations=(op("add_campaign_fact", fact=foreign_fact),),
        )

        res = await apply_in_context(ctx_a, prop, policy=policy())
        assert res.status in ("denied", "failed")
        assert res.reason_code == "campaign_boundary_violation"

        # Check Campaign B was completely untouched
        events_b_after = (await ctx_a.session.scalars(select(Event).where(Event.campaign_id == cid_b))).all()
        facts_b_after = (await ctx_a.session.scalars(q_facts_b)).all()
        assert len(events_b_after) == events_b_count
        assert len(facts_b_after) == facts_b_count

    play(settings, cid_a, [], scenario)
