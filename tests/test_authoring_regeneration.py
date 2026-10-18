# ruff: noqa: F811
import copy

from sqlalchemy import func, select

from app.core.authoring.contracts import DraftPatch
from app.core.authoring.edits import apply_edits
from app.core.authoring.regeneration import regenerate_location
from app.core.authoring.validation import validate_project
from app.core.world_generation.service import Orchestrator
from app.db.models import AuthorProject, CampaignSecret, Entity, WorldGenerationState
from app.gateway.coordination import InMemoryCoordination
from tests.layout_plan_pilot import TEMPLE_SPATIAL
from tests.test_authoring_validation import _prepared
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура


async def edit_tavern_map(s, pid):
    project = await s.get(AuthorProject, pid)
    spatial = copy.deepcopy(TEMPLE_SPATIAL)
    spatial["parts"] = [*spatial["parts"][:5], {"ref": "cellar", "name": "Новый погреб", "below": True}]
    patch = DraftPatch.model_validate(
        {"operations": [{"op": "edit_map", "location_ref": "loc_tavern", "spatial": spatial}]}
    )
    await apply_edits(s, project, patch, project.draft_revision, "map-edit")
    await s.commit()
    return project


async def tavern(s, cid):
    secret = await s.get(CampaignSecret, cid)
    return next(x for x in secret.plot["locations"] if x["id"] == "loc_tavern")["entity_id"]


def test_regenerated_map_replaces_old_one_atomically(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            await edit_tavern_map(s, pid)
            old_root = await tavern(s, cid)
            assert "layout:loc_tavern" in (await s.get(AuthorProject, pid)).dependencies["stale"]
        result = await regenerate_location(maker, pid, "loc_tavern", Orchestrator(InMemoryCoordination()))
        assert result["status"] == "ready"
        async with maker() as s:
            new_root_id = await tavern(s, cid)
            assert new_root_id != old_root and await s.get(Entity, old_root) is None
            root = await s.get(Entity, new_root_id)
            assert "cellar" in root.state["areas"] and "candidate_for" not in root.state
            entities = {e.id: e for e in await s.scalars(select(Entity).where(Entity.campaign_id == cid))}
            for npc in (e for e in entities.values() if e.kind == "creature"):
                assert npc.location_id in entities  # жители переехали, а не остались в удалённом участке
            assert not [e for e in entities.values() if e.location_id and e.location_id not in entities]
            project = await s.get(AuthorProject, pid)
            assert not [r for r in project.dependencies["stale"] if r.endswith("loc_tavern")]
            assert not [r for r in project.dependencies["stale"] if r == "route_port:r_port_tavern"]
            report = await validate_project(s, project)
            assert not report.errors, report.errors
            rows = list(await s.scalars(select(WorldGenerationState).where(WorldGenerationState.campaign_id == cid)))
            assert rows and all(r.status == "ready" and r.target_entity_id in entities for r in rows)

    _prepared(settings, body)


class Stuck:
    """A preparer that never finishes: the candidate cannot become ready."""

    async def prepare(self, maker, campaign_id, ref):
        return "pending"


def test_failed_candidate_keeps_previous_map(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            await edit_tavern_map(s, pid)
            old_root = await tavern(s, cid)
            before = await s.scalar(select(func.count()).select_from(Entity).where(Entity.campaign_id == cid))
        result = await regenerate_location(maker, pid, "loc_tavern", Stuck())
        assert result["status"] == "blocked"
        async with maker() as s:
            assert await tavern(s, cid) == old_root
            assert await s.get(Entity, old_root) is not None
            after = await s.scalar(select(func.count()).select_from(Entity).where(Entity.campaign_id == cid))
            assert after == before  # кандидат удалён, прежняя карта на месте, дублей нет
            assert "layout:loc_tavern" in (await s.get(AuthorProject, pid)).dependencies["stale"]

    _prepared(settings, body)


def test_maps_stage_with_star_rebuilds_every_location(settings, _fast_retry):
    from types import SimpleNamespace

    from app.core.authoring import jobs
    from app.core.authoring.runner import AuthorRunner
    from app.db.models import AuthorJob

    async def body(maker, pid, cid):
        async with maker() as s:
            secret = await s.get(CampaignSecret, cid)
            before = {x["id"]: x["entity_id"] for x in secret.plot["locations"]}
            project = await s.get(AuthorProject, pid)
            project.dependencies = {**project.dependencies, "materialize": "done"}
            await s.commit()
            receipt = await jobs.request_stage(s, project, "maps", "*", project.draft_revision, "all", regenerate=True)
            await s.commit()
        svc = SimpleNamespace(maker=maker, llm=None, bus=None, coordination=InMemoryCoordination())
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            job = await s.get(AuthorJob, receipt.job_id)
            assert job.status == "ready", job.error_code
            assert sorted(job.result["regenerated"]) == sorted(before)
            after = {x["id"]: x["entity_id"] for x in (await s.get(CampaignSecret, cid)).plot["locations"]}
            assert all(after[k] != v for k, v in before.items())  # каждая карта заменена новой

    _prepared(settings, body)
