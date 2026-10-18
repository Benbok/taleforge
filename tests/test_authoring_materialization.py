# ruff: noqa: F811
import asyncio

import pytest
from sqlalchemy import func, select

from app.content.yaml_io import load_file
from app.core.authoring.contracts import AuthorProjectCreate
from app.core.authoring.materialization import MaterializationError, ensure_actor, prepare_world
from app.core.authoring.projects import create_project
from app.core.world_generation.service import Orchestrator
from app.db.models import CampaignSecret, Character, Entity, GameSession, WorldGenerationState
from app.db.session import make_engine, make_sessionmaker
from app.gateway.coordination import InMemoryCoordination
from app.rules.dice import Dice
from app.tools.runtime import open_context
from tests.authoring_helpers import author
from tests.game import BASE, import_base
from tests.layout_plan_pilot import temple_plan
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура


def homed_plan():
    plan = temple_plan()
    for npc in plan["npcs"]:
        npc.setdefault("location_id", "loc_tavern")  # у каждого NPC авторского мира есть исходный дом
    return plan


def _prepared_project(settings, plan=None):
    import_base(settings)
    pack = load_file(BASE / "pack.yaml")

    async def go():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as s:
                owner = await author(s)
                project = await create_project(
                    s,
                    owner,
                    AuthorProjectCreate(title="W", pack_id=str(pack["id"]), pack_version=str(pack["version"])),
                )
                secret = await s.get(CampaignSecret, project.workspace_campaign_id)
                if secret is None:
                    secret = CampaignSecret(campaign_id=project.workspace_campaign_id)
                    s.add(secret)
                secret.plot = plan or homed_plan()
                await s.commit()
                return project.id, project.workspace_campaign_id
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _with_maker(settings, fn):
    async def go():
        engine = make_engine(settings.database_url)
        try:
            return await fn(make_sessionmaker(engine))
        finally:
            await engine.dispose()

    return asyncio.run(go())


async def _counts(maker):
    async with maker() as s:
        return {
            "entities": await s.scalar(select(func.count()).select_from(Entity)),
            "characters": await s.scalar(select(func.count()).select_from(Character)),
            "sessions": await s.scalar(select(func.count()).select_from(GameSession)),
        }


def test_full_preparation_materializes_everything_without_heroes(settings, _fast_retry):
    pid, cid = _prepared_project(settings)

    async def body(maker):
        report = await prepare_world(maker, pid, Orchestrator(InMemoryCoordination()))
        assert report.locations and all(a.status == "ready" for a in report.locations), report
        assert report.actors and all(a.status == "ready" for a in report.actors), report
        assert report.pending_rows == 0 and report.blocked_rows == 0 and report.complete
        counts = await _counts(maker)
        assert counts["characters"] == 0 and counts["sessions"] == 0
        async with maker() as s:
            names = {e.name for e in await s.scalars(select(Entity).where(Entity.campaign_id == cid))}
            assert {
                "Старый храм",
                "Тайник",
            } <= names  # места и их наполнение созданы, а не только перечислены в каркасе
            rows = list(await s.scalars(select(WorldGenerationState).where(WorldGenerationState.campaign_id == cid)))
            assert rows and all(r.status == "ready" for r in rows)
        return counts

    counts = _with_maker(settings, body)

    async def again(maker):
        report = await prepare_world(maker, pid, Orchestrator(InMemoryCoordination()))
        assert report.complete
        assert await _counts(maker) == counts  # повтор не дублирует сущности

    _with_maker(settings, again)


def test_actor_without_materialized_home_is_blocked_not_placed(settings):
    _pid, cid = _prepared_project(settings)

    async def body(maker):
        async with maker() as s:
            from app.db.models import Campaign

            ctx = await open_context(s, await s.get(Campaign, cid), Dice(seed=1), turn_id="t", seat_id=None)
            with pytest.raises(MaterializationError) as raised:
                await ensure_actor(ctx, "npc_warden")
            assert raised.value.code == "home_not_materialized"
        async with maker() as s:
            assert await s.scalar(select(func.count()).select_from(Entity).where(Entity.kind == "creature")) == 0

    _with_maker(settings, body)


def test_npc_without_home_is_blocked_while_other_maps_are_kept(settings, _fast_retry):
    plan = temple_plan()
    for npc in plan["npcs"]:
        if npc["id"] != "npc_guard":
            npc.setdefault("location_id", "loc_tavern")
    pid, _cid = _prepared_project(settings, plan)

    async def body(maker):
        report = await prepare_world(maker, pid, Orchestrator(InMemoryCoordination()))
        assert all(a.status == "ready" for a in report.locations)
        status = {a.ref: a for a in report.actors}
        assert status["npc_guard"].status == "blocked" and status["npc_guard"].reasons == ("home_not_materialized",)
        assert status["npc_warden"].status == "ready"
        assert not report.complete

    _with_maker(settings, body)
