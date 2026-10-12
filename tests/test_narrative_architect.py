"""Tests for architect cutover and Gate B director adaptation pipeline (Task 15)."""

import asyncio
import copy
from typing import Any

import pytest
from sqlalchemy import select

from app.agents import architect
from app.agents.llm import ScriptedLLM
from app.core import plot
from app.core.narrative.contracts import (
    AdaptationProposal,
    Ground,
    NarrativePolicy,
)
from app.core.narrative.service import NarrativeService
from app.db.models import Campaign, CampaignPlan, CampaignSecret, NarrativeWork
from app.db.narrative import ensure_state
from app.db.narrative_jobs import SqlNarrativeJobs
from app.db.session import make_sessionmaker
from app.tools.narrative.runtime import RuntimeNarrativeApplier
from app.tools.registry import ToolContext
from tests.game import QueueDice, import_base, party
from tests.test_plan import good_plan


class FakeBus:
    """Mock bus for publishing campaign updates."""

    async def publish(self, *args, **kwargs):
        pass


class FakeMasterService:
    """Mock MasterService for architect.revise tests."""

    def __init__(self, maker, llm=None):
        self.maker = maker
        self.llm = llm or ScriptedLLM([])
        self.bus = FakeBus()
        self.narrative_preparer = None
        self._recovered = False

    def signal_recovery(self) -> None:
        self._recovered = True


def initialized_plan() -> dict[str, Any]:
    p = copy.deepcopy(good_plan())
    p["acts"][0]["status"] = "active"
    p["acts"][1]["status"] = "pending"
    p["acts"][2]["status"] = "pending"
    for node in p["acts"][0].get("nodes", []):
        node["status"] = "open"
    for node in p["acts"][1].get("nodes", []):
        node["status"] = "open"
    for node in p["acts"][2].get("nodes", []):
        node["status"] = "open"
    return p


@pytest.fixture
def plan_campaign(settings, client, admin):
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _setup():
        async with maker() as s:
            assert await s.get(Campaign, cid) is not None
            p = initialized_plan()
            row = CampaignPlan(campaign_id=cid, version=1, content=p, note="init")
            s.add(row)
            secret = await s.get(CampaignSecret, cid)
            if not secret:
                secret = CampaignSecret(campaign_id=cid)
                s.add(secret)
            secret.plot = copy.deepcopy(p)
            await s.commit()

    asyncio.run(_setup())
    return c


def _make_ctx(session, campaign, call_key="k1") -> ToolContext:
    return ToolContext(
        session=session,
        campaign=campaign,
        world=None,
        dice=QueueDice([20]),
        game_session_id="sess-1",
        turn_id="turn-1",
        actor_seat_id=None,
        call_key=call_key,
    )


def test_architect_revise_replan_false_returns_none(settings, client, admin, plan_campaign):
    cid = plan_campaign["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            camp.settings = {**(camp.settings or {}), "replan": False}
            await s.commit()

        svc = FakeMasterService(maker)
        res = await architect.revise(svc, cid)
        assert res is None

    asyncio.run(_run())


def test_architect_revise_adaptive_delegates_to_narrative_path(settings, client, admin, plan_campaign):
    cid = plan_campaign["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            camp.settings = {**(camp.settings or {}), "replan": True}
            state = await ensure_state(s, cid)
            state.mode = "adaptive"
            await s.commit()

        svc = FakeMasterService(maker)
        res = await architect.revise(svc, cid)
        assert res is not None

        # Verify a narrative work item was enqueued instead of running legacy merge
        async with maker() as s:
            works = (await s.scalars(select(NarrativeWork).where(NarrativeWork.campaign_id == cid))).all()
            assert len(works) >= 1
            work = works[0]
            assert work.kind == "act_closed"
            assert work.scope == "future"
            assert work.status == "pending"

    asyncio.run(_run())


def test_architect_revise_strict_preserves_legacy_revision(settings, client, admin, plan_campaign):
    cid = plan_campaign["id"]
    maker = make_sessionmaker(client.app.state.engine)

    revision_args = {
        "summary": "культисты укрепили маяк",
        "acts": [
            {
                "id": "act2",
                "title": "Маяк",
                "goal": "Прорваться на маяк",
                "exit": "Культ разбит",
                "milestone_level": 3,
                "nodes": [
                    {
                        "id": "n_light",
                        "title": "Штурм маяка",
                        "status": "sketch",
                        "kind": "combat",
                        "location_id": "loc_light",
                        "summary": "Культ обороняет линзу маяка",
                    },
                    {
                        "id": "n_betrayal",
                        "title": "Измена",
                        "summary": "Смотритель выдаёт себя",
                    },
                ],
            },
            copy.deepcopy(good_plan()["acts"][2]),
        ],
    }
    tool_call = (plot.REVISE_TOOL, revision_args)
    llm = ScriptedLLM([{"text": "", "tool_calls": [tool_call]}])

    async def _run():
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            camp.settings = {**(camp.settings or {}), "replan": True}
            secret = await s.get(CampaignSecret, cid)
            p = copy.deepcopy(secret.plot)
            p["acts"][0]["status"] = "closed"
            secret.plot = p
            state = await ensure_state(s, cid)
            state.mode = "strict"
            await s.commit()

        svc = FakeMasterService(maker, llm=llm)

        res = await architect.revise(svc, cid)
        assert res is not None

        # Verify legacy CampaignPlan version was incremented
        async with maker() as s:
            plans = (await s.scalars(select(CampaignPlan).where(CampaignPlan.campaign_id == cid))).all()
            assert len(plans) == 2
            assert "культисты укрепили маяк" in str(plans[-1].note)

    asyncio.run(_run())


def test_gate_b_alliance_boundary_to_future_preparation(settings, client, admin, plan_campaign):
    """Gate B: Alliance boundary is enqueued, claimed, prepared by author, and applied to future situation."""
    cid = plan_campaign["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        async with maker() as s:
            from app.db.models import Event

            ev = Event(
                id="evt-alliance-1",
                campaign_id=cid,
                tool="alliance",
                payload={"alliance": True},
            )
            s.add(ev)
            camp = await s.get(Campaign, cid)
            camp.settings = {**(camp.settings or {}), "replan": True}
            state = await ensure_state(s, cid)
            state.mode = "adaptive"
            await s.commit()

        # 1. Enqueue an alliance boundary
        from app.core.narrative.contracts import BoundaryRecord, EvidenceRef
        from app.core.narrative.triggers import enqueue_boundaries

        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = _make_ctx(s, camp, call_key="gate_b_key")
            b = BoundaryRecord(
                campaign_id=cid,
                kind="relationship",
                source_id="alliance-npc-1",
                scope="future",
                evidence_refs=(EvidenceRef(campaign_id=cid, kind="event", source_id="evt-alliance-1"),),
                session_budget_ref="sess-gate-b",
            )
            work_ids = await enqueue_boundaries(ctx, (b,))
            await s.commit()

        assert len(work_ids) == 1
        work_id = work_ids[0]

        # 2. Setup mock author that proposes revising the future node
        class GateBAuthor:
            calls = 0

            async def propose(self, snapshot):
                self.calls += 1
                from app.core.narrative.contracts import FuturePlanEdit, FutureSituationPatch
                from tests.narrative_helpers import op

                patch = FutureSituationPatch(
                    edits=(
                        FuturePlanEdit(
                            kind="update_open_node",
                            act_id="act2",
                            node_id="n_light",
                            fields={"title": "Союзный маяк", "summary": "Встреча с союзником на маяке вместо штурма"},
                        ),
                    )
                )

                proposal = AdaptationProposal(
                    schema_version=1,
                    proposal_id=snapshot.proposal_id,
                    source=snapshot.source,
                    base=snapshot.base,
                    grounds=(
                        Ground(
                            kind="relationship",
                            evidence_refs=(EvidenceRef(campaign_id=cid, kind="event", source_id="evt-alliance-1"),),
                        ),
                    ),
                    summary="Адаптация маяка под заключённый союз",
                    operations=(op("revise_future_situation", patch=patch),),
                    read_set=snapshot.read_set,
                )
                return proposal

        from app.tools.narrative.reader import DbNarrativeReader
        from tests.narrative_helpers import FakeClock

        clock = FakeClock()
        reader = DbNarrativeReader(maker, policy_provider=lambda: NarrativePolicy(mode="adaptive"))
        jobs = SqlNarrativeJobs(maker, max_author_slots=2)
        applier = RuntimeNarrativeApplier(
            maker,
            bus=FakeBus(),
            coordination=None,
            policy_provider=lambda _cid: NarrativePolicy(mode="adaptive"),
            clock=clock,
        )
        service = NarrativeService(
            reader=reader,
            author=GateBAuthor(),
            applier=applier,
            jobs=jobs,
            clock=clock,
        )

        # 3. Execute narrative service: prepare draft then apply draft
        prep_report = await service.prepare_once(cid)
        assert prep_report is not None
        assert prep_report.status == "prepared"

        apply_report = await service.prepare_once(cid)
        assert apply_report is not None
        assert apply_report.status == "applied", f"reason={apply_report.reason_code}"

        # 4. Verify future node updated in CampaignSecret.plot
        async with maker() as s:
            secret = await s.get(CampaignSecret, cid)
            plot_data = secret.plot
            # Find n_light node
            node_found = None
            for act_data in plot_data.get("acts", []):
                for node_data in act_data.get("nodes", []):
                    if node_data.get("id") == "n_light":
                        node_found = node_data
            assert node_found is not None
            assert node_found["title"] == "Союзный маяк"
            assert "союзником" in node_found["summary"]

            work_row = await s.get(NarrativeWork, work_id)
            assert work_row.status == "applied"

    asyncio.run(_run())
