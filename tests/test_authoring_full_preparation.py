# ruff: noqa: F811
from types import SimpleNamespace

from sqlalchemy import select

from app.core.authoring import jobs
from app.core.authoring.runner import AuthorRunner
from app.db.models import AuthorJob, AuthorProject
from app.gateway.coordination import InMemoryCoordination
from tests.test_authoring_materialization import _prepared_project, _with_maker, homed_plan
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура


def test_materialize_stage_runs_through_the_runner(settings, _fast_retry):
    pid, _cid = _prepared_project(settings, homed_plan())

    async def body(maker):
        svc = SimpleNamespace(maker=maker, llm=None, bus=None, coordination=InMemoryCoordination())
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            receipt = await jobs.request_stage(s, project, "materialize", None, project.draft_revision, "m1")
            await s.commit()
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            job = await s.get(AuthorJob, receipt.job_id)
            assert job.status == "ready", job.error_code
            assert job.result["report"]["pending_rows"] == 0
            assert all(a["status"] == "ready" for a in job.result["report"]["locations"])
            assert (await s.scalars(select(AuthorProject.id))).first() == pid

    _with_maker(settings, body)
