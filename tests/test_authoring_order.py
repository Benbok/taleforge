# ruff: noqa: F811
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.core.authoring import jobs
from app.core.authoring.runner import AuthorRunner
from app.core.campaigns import Conflict
from app.db.models import AuthorJob, AuthorProject, CampaignSecret, Entity, GeographyNode
from app.gateway.coordination import InMemoryCoordination
from tests.test_authoring_materialization import _prepared_project, _with_maker, homed_plan
from tests.test_authoring_pipeline import LORE, Llm
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура


async def request(maker, pid, stage, key, **kw):
    async with maker() as s:
        project = await s.get(AuthorProject, pid)
        receipt = await jobs.request_stage(s, project, stage, None, project.draft_revision, key, **kw)
        await s.commit()
        return receipt


def svc_for(maker, llm=None):
    return SimpleNamespace(maker=maker, llm=llm or Llm(), bus=None, coordination=InMemoryCoordination())


def test_stage_needs_its_upstream_ready(settings):
    pid, cid = _prepared_project(settings, homed_plan())

    async def body(maker):
        with pytest.raises(Conflict, match="geography"):
            await request(maker, pid, "materialize", "m1")
        with pytest.raises(Conflict, match="materialize"):
            await request(maker, pid, "maps", "x1")
        async with maker() as s:
            (await s.get(CampaignSecret, cid)).plot = {}
            await s.commit()
        with pytest.raises(Conflict, match="plot"):
            await request(maker, pid, "geography", "g1")  # нет каркаса — нечего компилировать
        await request(maker, pid, "lore", "l1")  # первый этап и проверка доступны всегда
        await request(maker, pid, "validate", "v1")

    _with_maker(settings, body)


def test_new_lore_variant_marks_built_stages_stale(settings, _fast_retry):
    pid, _cid = _prepared_project(settings, homed_plan())

    async def body(maker):
        svc = svc_for(maker)
        await request(maker, pid, "lore", "l1")
        await AuthorRunner(svc).run_due()
        await request(maker, pid, "geography", "g1")
        await AuthorRunner(svc).run_due()
        svc.llm.args = {**LORE, "tone": "иной"}
        await request(maker, pid, "lore", "l2", regenerate=True)
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            stale = (await s.get(AuthorProject, pid)).dependencies["stale"]
        assert "stage:geography" in stale  # география построена на прежнем результате
        await request(maker, pid, "geography", "g2", regenerate=True)
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            assert "stage:geography" not in (await s.get(AuthorProject, pid)).dependencies["stale"]

    _with_maker(settings, body)


def test_new_plot_clears_the_materialized_world(settings, _fast_retry, monkeypatch):
    pid, cid = _prepared_project(settings, homed_plan())

    async def fake_generate(svc, world_id, note="", structure_id=None, **kw):
        return "plan_new"

    monkeypatch.setattr("app.agents.architect.generate", fake_generate)

    async def body(maker):
        svc = svc_for(maker)
        for stage in ("geography", "materialize"):
            await request(maker, pid, stage, f"{stage}-1")
            await AuthorRunner(svc).run_due()
        async with maker() as s:
            assert await s.scalar(select(func.count()).select_from(Entity).where(Entity.campaign_id == cid))
        receipt = await request(maker, pid, "plot", "p1")
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            job = await s.get(AuthorJob, receipt.job_id)
            assert job.status == "ready" and job.result["cleared_entities"] > 0
            assert await s.scalar(select(func.count()).select_from(Entity).where(Entity.campaign_id == cid)) == 0
            assert (
                await s.scalar(select(func.count()).select_from(GeographyNode).where(GeographyNode.campaign_id == cid))
                == 0
            )
            stale = (await s.get(AuthorProject, pid)).dependencies["stale"]
            assert {"stage:geography", "stage:materialize"} <= set(stale)

    _with_maker(settings, body)
