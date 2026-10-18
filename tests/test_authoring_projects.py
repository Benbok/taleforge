import asyncio

import pytest
from sqlalchemy import func, select

from app.core.campaigns import AccessDenied, NotFound, get_viewer
from app.db.models import Campaign, Character, GameSession, Invite, Message, NarrativeState, User
from app.db.session import make_engine, make_sessionmaker
from tests.authoring_helpers import author
from tests.test_api import make_campaign


def test_author_project_is_not_a_game(settings):
    from app.core.authoring.contracts import AuthorProjectCreate
    from app.core.authoring.projects import create_project, require_project

    async def run():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as session:
                owner = await author(session)
                project = await create_project(session, owner, AuthorProjectCreate(title="World"))
                world = await session.get(Campaign, project.workspace_campaign_id)
                assert world.purpose == "author_workspace"
                assert [seat.role for seat in world.seats] == ["master"]
                assert all(seat.user_id is None for seat in world.seats)
                assert project.draft_revision >= 1
                assert await require_project(session, owner, project.id) is project
                for table in (Character, GameSession, Invite, Message, NarrativeState):
                    assert await session.scalar(select(func.count()).select_from(table)) == 0
                with pytest.raises(NotFound):
                    await get_viewer(session, owner, world.id)
                outsider = await author(session, "outsider")
                with pytest.raises(NotFound):
                    await require_project(session, outsider, project.id)
                player = await author(session, "player", "player")
                with pytest.raises(AccessDenied):
                    await create_project(session, player, AuthorProjectCreate(title="Denied"))
                with pytest.raises(NotFound):
                    await require_project(session, player, project.id)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_game_api_hides_workspace(client, admin, settings):
    from app.core.authoring.contracts import AuthorProjectCreate
    from app.core.authoring.projects import create_project

    game = make_campaign(client, admin)

    async def prepare():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as session:
                owner = await session.scalar(select(User).where(User.name == "Arty"))
                project = await create_project(session, owner, AuthorProjectCreate(title="Hidden world"))
                assert (await session.get(Campaign, game["id"])).purpose == "game"
                await session.commit()
                return project.workspace_campaign_id
        finally:
            await engine.dispose()

    cid = asyncio.run(prepare())
    response = client.get("/api/campaigns", headers=admin)
    assert response.status_code == 200
    assert game["id"] in response.text
    assert cid not in response.text
    assert client.get(f"/api/campaigns/{cid}", headers=admin).status_code == 404
    assert client.post(f"/api/campaigns/{cid}/invites", json={}, headers=admin).status_code == 404


def test_world_edits_advance_draft_but_job_status_does_not(settings):
    from app.core.authoring.contracts import AuthorProjectCreate
    from app.core.authoring.projects import author_write, create_project
    from app.core.campaigns import Conflict
    from app.db.models import AuthorJob, CampaignSecret

    async def run():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as session:
                owner = await author(session)
                project = await create_project(session, owner, AuthorProjectCreate(title="World"))
                await session.commit()
                before = project.draft_revision
                await author_write(session, project, before)
                secret = await session.get(CampaignSecret, project.workspace_campaign_id)
                secret.setting = {"theme": "forest"}
                await session.commit()
                await session.refresh(project)
                assert project.draft_revision == before + 1
                with pytest.raises(Conflict):
                    await author_write(session, project, before)
                await session.rollback()
                await session.refresh(project)
                job = AuthorJob(
                    project_id=project.id,
                    stage="lore",
                    input_digest="a",
                    request_digest="b",
                    source_revision=project.draft_revision,
                    request_key="first",
                )
                session.add(job)
                await session.commit()
                job.status = "running"
                await session.commit()
                await session.refresh(project)
                assert project.draft_revision == before + 1
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_game_recovery_ignores_author_world(client, settings):
    from app.core.authoring.contracts import AuthorProjectCreate
    from app.core.authoring.projects import create_project
    from app.db.models import MasterTurn, Scene

    async def run():
        maker = client.app.state.master.maker
        async with maker() as session:
            owner = await author(session)
            project = await create_project(session, owner, AuthorProjectCreate(title="Workbench"))
            cid = project.workspace_campaign_id
            # Even accidental runtime residue must not turn a workspace into a game.
            session.add(
                Scene(
                    campaign_id=cid,
                    mode="combat",
                    state={"deadline": 9999999999, "rest_votes": {"v": {"id": "v", "deadline": 9999999999}}},
                )
            )
            turn = MasterTurn(campaign_id=cid, status="running")
            session.add(turn)
            await session.commit()
            turn_id = turn.id
        master = client.app.state.master
        await master.resume_timers()
        await client.app.state.rest.resume()
        await master.recover(startup=True)
        assert cid not in master._timers
        assert "v" not in client.app.state.rest._timers
        async with maker() as session:
            assert (await session.get(MasterTurn, turn_id)).status == "running"
            assert (
                await session.scalar(select(func.count()).select_from(Message).where(Message.campaign_id == cid)) == 0
            )

    # Run against the same event loop as the application's services.
    client.portal.call(run)


def test_narrative_recovery_does_not_claim_author_work(settings):
    from app.core.authoring.contracts import AuthorProjectCreate
    from app.core.authoring.projects import create_project
    from app.db.narrative_jobs import SqlNarrativeJobs
    from tests.narrative_helpers import FakeClock, boundary

    async def run():
        engine = make_engine(settings.database_url)
        try:
            maker = make_sessionmaker(engine)
            async with maker() as session:
                owner = await author(session)
                project = await create_project(session, owner, AuthorProjectCreate(title="World"))
                await session.commit()
                cid = project.workspace_campaign_id
            jobs = SqlNarrativeJobs(maker)
            await jobs.enqueue(boundary(campaign_id=cid))
            assert await jobs.claim(FakeClock()()) is None
        finally:
            await engine.dispose()

    asyncio.run(run())
