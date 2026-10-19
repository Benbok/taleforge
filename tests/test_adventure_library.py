# ruff: noqa: F811
import asyncio

from sqlalchemy import func, select

from app.core.authoring.materialization import prepare_world
from app.core.authoring.publication import publish_project
from app.core.authoring.validation import store_report, validate_project
from app.core.security import create_token
from app.core.world_generation.service import Orchestrator
from app.db.models import AuthorProject, Campaign, LlmCall
from app.db.session import make_engine, make_sessionmaker
from app.gateway.coordination import InMemoryCoordination
from tests.conftest import login
from tests.test_authoring_materialization import _prepared_project
from tests.test_authoring_validation import full_plan
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура

LAUNCH = {"options": {"name": "Игра A", "players": 2, "master": {"type": "agent"}}, "request_key": "go-1"}


def publish_in_db(settings):
    pid, _cid = _prepared_project(settings, full_plan())

    async def go():
        engine = make_engine(settings.database_url)
        maker = make_sessionmaker(engine)
        try:
            report = await prepare_world(maker, pid, Orchestrator(InMemoryCoordination()))
            assert report.complete
            async with maker() as s:
                project = await s.get(AuthorProject, pid)
                await store_report(s, project, await validate_project(s, project))
                await s.commit()
                version = await publish_project(s, project, project.draft_revision, "pub")
                await s.commit()
                return project.owner_id, version.id
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_library_lists_only_own_summaries_and_launch_is_idempotent(client, admin, root, settings, _fast_retry):
    owner_id, version_id = publish_in_db(settings)
    owner = {"Authorization": f"Bearer {create_token(owner_id, settings.jwt_secret, 1)}"}
    listing = client.get("/api/adventures", headers=owner)
    assert listing.status_code == 200
    items = listing.json()
    assert [i["id"] for i in items] == [version_id] and items[0]["version"] == 1
    assert items[0]["project_title"] == "W"  # рабочее имя проекта — чтобы автор различал свои приключения
    assert "bundle" not in listing.text and "entities" not in listing.text
    assert "secret" not in str(items[0]["public_summary"]).lower()

    client.post("/api/admin/users", json={"name": "Other", "password": "secret1"}, headers=root)
    other = login(client, "Other", "secret1")
    assert client.get("/api/adventures", headers=other).json() == []
    assert client.post(f"/api/adventures/{version_id}/games", json=LAUNCH, headers=other).status_code == 404
    assert client.get("/api/adventures").status_code == 401

    first = client.post(f"/api/adventures/{version_id}/games", json=LAUNCH, headers=owner)
    assert first.status_code == 201, first.text
    again = client.post(f"/api/adventures/{version_id}/games", json=LAUNCH, headers=owner)
    assert again.json()["campaign_id"] == first.json()["campaign_id"]
    changed = {**LAUNCH, "options": {**LAUNCH["options"], "players": 3}}
    assert client.post(f"/api/adventures/{version_id}/games", json=changed, headers=owner).status_code == 409

    game_id = first.json()["campaign_id"]
    assert client.get(f"/api/campaigns/{game_id}", headers=owner).status_code == 200
    ids = [c["id"] for c in client.get("/api/campaigns", headers=owner).json()]
    assert ids == [game_id]  # игра в списке, рабочий мир — нет

    async def check():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as s:
                games = await s.scalar(select(func.count()).select_from(Campaign).where(Campaign.purpose == "game"))
                assert games == 1
                assert (
                    await s.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.campaign_id == game_id)) == 0
                )
        finally:
            await engine.dispose()

    asyncio.run(check())
