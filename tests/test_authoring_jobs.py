import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.core.authoring import jobs
from app.core.authoring.contracts import AuthorProjectCreate
from app.core.authoring.projects import create_project
from app.core.campaigns import Conflict
from app.db.models import AuthorJob, LlmCall
from app.db.session import make_engine, make_sessionmaker
from tests.authoring_helpers import author


def _run(settings, body):
    async def go():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as session:
                owner = await author(session)
                project = await create_project(session, owner, AuthorProjectCreate(title="W", budget_usd=1.0))
                await session.commit()
                await body(session, project)
        finally:
            await engine.dispose()

    asyncio.run(go())


def test_request_key_is_idempotent(settings):
    async def body(session, project):
        a = await jobs.request_stage(session, project, "lore", None, project.draft_revision, "k1")
        b = await jobs.request_stage(session, project, "lore", None, project.draft_revision, "k1")
        assert a.job_id == b.job_id
        with pytest.raises(Conflict):
            await jobs.request_stage(session, project, "plot", None, project.draft_revision, "k1")
        with pytest.raises(Conflict):
            await jobs.request_stage(session, project, "lore", None, project.draft_revision + 5, "k2")

    _run(settings, body)


def test_same_input_digest_is_one_job_and_regenerate_makes_variant(settings):
    async def body(session, project):
        rev = project.draft_revision
        a = await jobs.request_stage(session, project, "lore", None, rev, "k1")
        b = await jobs.request_stage(session, project, "lore", None, rev, "k2")
        assert a.job_id == b.job_id
        token = await jobs.claim(session, a.job_id)
        assert await jobs.finish(session, a.job_id, token, "ready", result={"x": 1})
        again = await jobs.request_stage(session, project, "lore", None, rev, "k3")
        assert again.job_id == a.job_id and again.status == "ready"
        variant = await jobs.request_stage(session, project, "lore", None, rev, "k4", regenerate=True)
        assert variant.job_id != a.job_id
        old = await session.get(AuthorJob, a.job_id)
        assert old.status == "ready" and old.result == {"x": 1}

    _run(settings, body)


def test_lease_exclusive_and_expired_lease_recovers(settings):
    async def body(session, project):
        receipt = await jobs.request_stage(session, project, "lore", None, project.draft_revision, "k")
        first = await jobs.claim(session, receipt.job_id)
        assert first
        assert await jobs.claim(session, receipt.job_id) is None  # второй worker не берёт
        await session.execute(
            update(AuthorJob).where(AuthorJob.id == receipt.job_id).values(lease_until=datetime.now(UTC) - timedelta(1))
        )
        assert receipt.job_id in await jobs.due_job_ids(session)
        second = await jobs.claim(session, receipt.job_id)
        assert second and second != first
        # старый worker не сохраняет результат поверх нового владельца
        assert not await jobs.finish(session, receipt.job_id, first, "ready", result={"old": True})
        assert await jobs.finish(session, receipt.job_id, second, "ready", result={"new": True})
        assert (await session.get(AuthorJob, receipt.job_id)).result == {"new": True}

    _run(settings, body)


def test_budget_reservation_blocks_and_unknown_cost_is_visible(settings):
    async def body(session, project):
        receipt = await jobs.request_stage(session, project, "lore", None, project.draft_revision, "k")
        assert await jobs.reserve(session, project, receipt.job_id, 0.5)
        assert not await jobs.reserve(session, project, receipt.job_id, 5.0)
        session.add(
            LlmCall(
                campaign_id=project.workspace_campaign_id,
                purpose="lore",
                model="m",
                author_job_id=receipt.job_id,
                cost=0.2,
                cost_known=False,
            )
        )
        await session.flush()
        view = await jobs.stage_view(session, project.id, full=False)
        assert view.spent_usd == pytest.approx(0.2)
        assert view.cost_unknown is True
        assert view.content is None
        assert {s.stage for s in view.stages} == set(jobs.STAGES)

    _run(settings, body)
