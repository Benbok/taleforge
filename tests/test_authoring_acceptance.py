# ruff: noqa: F811
"""Author → prepare → edit → validate → publish → two independent games, through the public API.

The plan comes from a fixture instead of a live architect call: the suite never talks to a model.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select, update

from app.content.yaml_io import load_file
from app.core.authoring import jobs
from app.core.authoring.runner import AuthorRunner
from app.core.geography.travel import travel_route
from app.db.models import AuthorJob, AuthorProject, Campaign, CampaignSecret, Entity, LlmCall
from app.db.session import make_engine, make_sessionmaker
from app.gateway.coordination import InMemoryCoordination
from tests.game import BASE, import_base
from tests.test_adventure_instances import OPTIONS  # noqa: F401
from tests.test_api import make_campaign
from tests.test_geography_travel import context, hero
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура

FIXTURE = Path(__file__).parent / "fixtures" / "authoring_adventure.json"
SECRET_NAMES = ("Бертольд", "Марта", "Лис")


def maker_run(settings, body):
    async def go():
        engine = make_engine(settings.database_url)
        try:
            return await body(make_sessionmaker(engine))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def run_jobs(settings):
    async def body(maker):
        svc = SimpleNamespace(maker=maker, llm=None, bus=None, coordination=InMemoryCoordination())
        await AuthorRunner(svc).run_due()

    maker_run(settings, body)


def revision(client, admin, pid):
    return client.get(f"/api/author/projects/{pid}", headers=admin).json()["project"]["draft_revision"]


def prepare(client, admin, pid, stage, key):
    r = client.post(
        f"/api/author/projects/{pid}/prepare",
        json={"stage": stage, "expected_revision": revision(client, admin, pid), "request_key": key},
        headers=admin,
    )
    assert r.status_code == 202, r.text
    return r.json()


def stage_status(client, admin, pid):
    view = client.get(f"/api/author/projects/{pid}", headers=admin).json()
    return {s["stage"]: s["status"] for s in view["preparation"]["stages"]}


def count_entities(settings, cid):
    async def body(maker):
        async with maker() as s:
            return await s.scalar(select(func.count()).select_from(Entity).where(Entity.campaign_id == cid))

    return maker_run(settings, body)


def edit(client, admin, pid, ops, key):
    r = client.post(
        f"/api/author/projects/{pid}/edits",
        json={"patch": {"operations": ops}, "expected_revision": revision(client, admin, pid), "request_key": key},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    return r.json()


def validate_and_publish(client, admin, pid, key):
    client.post(f"/api/author/projects/{pid}/validate?view=full", headers=admin)
    return client.post(
        f"/api/author/projects/{pid}/publish",
        json={"expected_revision": revision(client, admin, pid), "request_key": key},
        headers=admin,
    )


def launch(client, admin, version_id, name, key):
    r = client.post(
        f"/api/adventures/{version_id}/games",
        json={"options": {"name": name, "players": 2, "master": {"type": "agent"}}, "request_key": key},
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()["campaign_id"]


def test_author_to_independent_games(monkeypatch, client, admin, settings, _fast_retry):
    monkeypatch.setattr(AuthorRunner, "start", lambda self: None)  # jobs run only when the test says so
    import_base(settings)
    pack = load_file(BASE / "pack.yaml")
    created = client.post(
        "/api/author/projects",
        json={"title": "Пещеры Шёпота", "pack_id": str(pack["id"]), "pack_version": str(pack["version"])},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]

    async def put_plan(maker):
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            (await s.get(CampaignSecret, project.workspace_campaign_id)).plot = json.loads(FIXTURE.read_text("utf-8"))
            await s.commit()
            return project.workspace_campaign_id

    workspace = maker_run(settings, put_plan)

    # конкурирующие запросы одного этапа — одна работа; рабочий мир не виден в играх
    first = prepare(client, admin, pid, "geography", "g1")
    second = prepare(client, admin, pid, "geography", "g2")
    assert first["job_id"] == second["job_id"]
    run_jobs(settings)
    assert stage_status(client, admin, pid)["geography"] == "ready"

    # перезапуск посреди этапа: воркер умер с просроченной арендой, новый runner дорабатывает без дублей
    mat = prepare(client, admin, pid, "materialize", "m1")

    async def crash(maker):
        async with maker() as s:
            token = await jobs.claim(s, mat["job_id"])
            assert token
            await s.execute(
                update(AuthorJob)
                .where(AuthorJob.id == mat["job_id"])
                .values(lease_until=datetime.now(UTC) - timedelta(hours=1))
            )
            await s.commit()

    maker_run(settings, crash)
    run_jobs(settings)
    assert stage_status(client, admin, pid)["materialize"] == "ready"
    built = count_entities(settings, workspace)
    again = prepare(client, admin, pid, "materialize", "m2")
    assert again["job_id"] == mat["job_id"] and again["status"] == "ready"
    run_jobs(settings)
    assert count_entities(settings, workspace) == built  # повтор не дублирует

    # ручная правка не перестраивает карту; секреты не раскрываются без явного режима
    result = edit(
        client,
        admin,
        pid,
        [{"op": "update_plot_object", "ref": "npc_warden", "fields": {"name": "Бертольд Седой"}}],
        "e1",
    )
    assert result["applied"] and result["affected"] == []
    summary = client.get(f"/api/author/projects/{pid}", headers=admin).text
    assert not any(name in summary for name in SECRET_NAMES)
    assert client.get("/api/campaigns", headers=admin).json() == []

    # проверка и публикация v1
    published = validate_and_publish(client, admin, pid, "p1")
    assert published.status_code == 201, published.text
    v1 = published.json()
    assert validate_and_publish(client, admin, pid, "p1").json()["id"] == v1["id"]  # повтор — та же версия
    library = client.get("/api/adventures", headers=admin)
    assert library.status_code == 200 and "bundle" not in library.text
    assert not any(name in library.text for name in SECRET_NAMES)

    # два независимых запуска, повтор запуска не создаёт третий
    game_a = launch(client, admin, v1["id"], "A", "la")
    game_b = launch(client, admin, v1["id"], "B", "lb")
    assert launch(client, admin, v1["id"], "A", "la") == game_a
    assert game_a != game_b
    assert sorted(c["id"] for c in client.get("/api/campaigns", headers=admin).json()) == sorted([game_a, game_b])

    async def play(maker):
        async with maker() as s:
            area_ids = {}
            for e in await s.scalars(select(Entity).where(Entity.campaign_id == game_a)):
                if e.name == "Пещера Обвала":
                    area_ids["crawl"] = e.state["areas"]["part_crawl"]
                if e.name == "Гладкие туннели":
                    area_ids["junction"] = e.state["areas"]["part_junction"]
            h = await hero(s, game_a, "Бран", area_ids["crawl"])
            await s.commit()
            ctx = await context(s, game_a)
            there = await travel_route(ctx, "r_crawl", [h])
            assert there.failure_code is None and there.destination_area_id == area_ids["junction"]
            back = await travel_route(ctx, "r_crawl", [h])
            assert back.failure_code is None and back.destination_area_id == area_ids["crawl"]
            await s.commit()
            # в A ключ забирают, судьба NPC меняется; B и опубликованный источник не меняются
            in_a = list(await s.scalars(select(Entity).where(Entity.campaign_id == game_a)))
            await s.delete(next(e for e in in_a if (e.state or {}).get("item_ref") == "item_key"))
            npc = next(e for e in in_a if e.kind == "creature")
            npc.state = {**npc.state, "hp": 0, "dead": True}
            await s.commit()
            for other in (game_b, workspace):
                found = list(await s.scalars(select(Entity).where(Entity.campaign_id == other)))
                assert [e for e in found if (e.state or {}).get("item_ref") == "item_key"]
                assert all(e.state.get("hp", 1) > 0 for e in found if e.kind == "creature")
            assert (
                await s.scalar(
                    select(func.count()).select_from(LlmCall).where(LlmCall.campaign_id.in_([game_a, game_b]))
                )
                == 0
            )

    maker_run(settings, play)

    # v2 с новым содержанием: игры A и B остаются на v1
    edit(client, admin, pid, [{"op": "set_lore", "fields": {"tone": "ещё мрачнее"}}], "e2")
    stale = client.get(f"/api/author/projects/{pid}", headers=admin).json()["preparation"]["stale"]
    assert stale == ["stage:plot"]
    blocked = validate_and_publish(client, admin, pid, "p-blocked")
    assert blocked.status_code == 409 and blocked.json()["detail"] == "publication_blocked"
    accepted = client.post(
        f"/api/author/projects/{pid}/edits/accept-stale",
        json={"refs": stale, "expected_revision": revision(client, admin, pid), "request_key": "acc"},
        headers=admin,
    )
    assert accepted.status_code == 200
    v2 = validate_and_publish(client, admin, pid, "p2")
    assert v2.status_code == 201 and v2.json()["version"] == 2 and v2.json()["id"] != v1["id"]

    async def versions(maker):
        async with maker() as s:
            return {
                c.id: c.adventure_version_id
                for c in await s.scalars(select(Campaign).where(Campaign.purpose == "game"))
            }

    assert maker_run(settings, versions) == {game_a: v1["id"], game_b: v1["id"]}

    # обычное создание кампании не требует авторского проекта и работает рядом
    legacy = make_campaign(client, admin)
    assert legacy["id"] not in (game_a, game_b)
