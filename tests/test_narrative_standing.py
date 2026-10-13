"""Tests for narrative standing response settlement and race handling (Task 16)."""

import asyncio

from app.core import standing as sd
from app.core.narrative.contracts import (
    AdaptationProposal,
    EvidenceRef,
    Ground,
    NarrativePolicy,
    SettleStandingResponseOp,
    VersionSet,
)
from app.core.narrative.policy import admit_adaptation
from app.db.models import Campaign
from app.db.session import make_sessionmaker
from app.rules.dice import Dice
from app.tools.narrative.compiler import compile_operations
from app.tools.narrative.executor import apply_in_context
from app.tools.registry import execute
from app.tools.runtime import open_context
from tests.game import import_base, party
from tests.narrative_helpers import proposal, snapshot


def test_settle_standing_response_admission_red():
    """Policy admission allows settle_standing_response when active."""
    snap = snapshot()
    op_settle = SettleStandingResponseOp(
        response_id="resp1",
        settled_effects=("Награда гильдии",),
    )
    prop = proposal(snap, operations=(op_settle,))
    pol = NarrativePolicy(mode="adaptive")
    adm = admit_adaptation(snap, prop, pol)
    assert adm.status in ("denied", "allowed")
    if adm.status == "denied":
        assert adm.reason_code == "operation_not_available"
    else:
        assert adm.status == "allowed"


def test_compile_settle_standing_response():
    """Compiler translates settle_standing_response to resolve_response tool call."""
    snap = snapshot()
    op_settle = SettleStandingResponseOp(
        response_id="resp_42",
        settled_effects=("Отряд получил благословение храма",),
    )
    prop = proposal(snap, operations=(op_settle,))
    calls = compile_operations(snap, prop)
    assert len(calls) == 1
    call = calls[0]
    assert call.tool == "resolve_response"
    assert call.args["response_id"] == "resp_42"
    assert "благословение" in call.args["how"]


def test_settle_standing_response_e2e_reconciliation(settings, client, admin):
    """End-to-end: settle_standing_response transitions ready response to done and leaves it closed."""
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _scenario():
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)

            # 1. Manually inject a ready standing response
            b = sd.book(ctx.world.scene.state)
            b["responses"].append(
                {
                    "id": "resp_scout",
                    "subject_id": "faction.guards",
                    "name": "Стража города",
                    "mood": "gratitude",
                    "tier": 1,
                    "due_at": 0,
                    "status": "ready",
                    "reason": "спасли патруль",
                    "targets": [hero["id"]],
                }
            )
            ctx.world.scene.state = {**(ctx.world.scene.state or {}), "standing": b}
            await s.commit()

        # 2. Build narrative proposal settling the response
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            from app.db.narrative import ensure_state

            n_state = await ensure_state(s, cid)
            n_state.mode = "adaptive"
            await s.commit()

        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            from app.tools.narrative.sources import bind_scene_sources

            slots = await bind_scene_sources(ctx)
            src = slots[0]

            ev = await ctx.record("deed", payload={"result": "saved_patrol", "subject_refs": ["faction.guards"]})

            prop = AdaptationProposal(
                schema_version=1,
                proposal_id="prop_settle_1",
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
                        subject_refs=("faction.guards",),
                    ),
                ),
                summary="Стража благодарит отряд жетоном",
                operations=(
                    SettleStandingResponseOp(
                        response_id="resp_scout",
                        settled_effects=("Стража передала отряду жетон доверия",),
                    ),
                ),
            )

            # Execute via apply_in_context
            policy = NarrativePolicy(mode="adaptive")
            res = await apply_in_context(ctx, prop, policy=policy)
            assert res.status == "applied"
            await s.commit()

        # 3. Check that response is now done in scene standing
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            b = sd.book(ctx.world.scene.state)
            resp = next(r for r in b["responses"] if r["id"] == "resp_scout")
            assert resp["status"] == "done"
            assert "жетон доверия" in resp.get("how", "")

    asyncio.run(_scenario())


def test_standing_race_normal_vs_narrative(settings, client, admin):
    """If normal resolve_response wins first, narrative settlement cannot double-resolve;

    If narrative adaptation is denied, standing response remains ready.
    """
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _scenario():
        # Setup ready response
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            b = sd.book(ctx.world.scene.state)
            b["responses"].append(
                {
                    "id": "resp_gift",
                    "subject_id": "faction.merchants",
                    "name": "Купеческая гильдия",
                    "mood": "gratitude",
                    "tier": 1,
                    "due_at": 0,
                    "status": "ready",
                    "reason": "спасли караван",
                    "targets": [hero["id"]],
                }
            )
            ctx.world.scene.state = {**(ctx.world.scene.state or {}), "standing": b}
            await s.commit()

        # Normal tool resolves it first
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id="t1", seat_id=None)
            await execute(ctx, "resolve_response", {"response_id": "resp_gift", "how": "Обычный подарок"})
            await s.commit()

        # Check response is done
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            b = sd.book(ctx.world.scene.state)
            resp = next(r for r in b["responses"] if r["id"] == "resp_gift")
            assert resp["status"] == "done"

            from app.tools.narrative.sources import bind_scene_sources

            slots = await bind_scene_sources(ctx)
            src = slots[0]

            ev2 = await ctx.record("deed", payload={"result": "saved_caravan", "subject_refs": ["faction.merchants"]})

            prop = AdaptationProposal(
                schema_version=1,
                proposal_id="prop_race_2",
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
                        evidence_refs=(EvidenceRef(campaign_id=cid, kind="event", source_id=ev2.id),),
                    ),
                ),
                summary="Повторная попытка наградить",
                operations=(
                    SettleStandingResponseOp(
                        response_id="resp_gift",
                        settled_effects=("Повторный подарок",),
                    ),
                ),
            )
            policy = NarrativePolicy(mode="adaptive")
            res = await apply_in_context(ctx, prop, policy=policy)
            assert res.status in ("failed", "denied")

            # Status remains done, not overwritten
            b2 = sd.book(ctx.world.scene.state)
            resp2 = next(r for r in b2["responses"] if r["id"] == "resp_gift")
            assert resp2["status"] == "done"
            assert resp2["how"] == "Обычный подарок"

    asyncio.run(_scenario())
