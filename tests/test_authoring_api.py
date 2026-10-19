import asyncio
import json

from sqlalchemy import func, select

from app.agents.llm import LLMReply
from app.db.models import AuthorJob, CampaignSecret, LlmCall
from app.db.session import make_engine, make_sessionmaker
from tests.conftest import login

PLAN = {
    "locations": [
        {"id": "loc_secret_vault", "name": "Тайник", "mood": "сыро", "role": "тайное", "secret": "здесь тело"}
    ],
    "npcs": [{"id": "npc_traitor", "name": "Предатель", "location_id": "loc_secret_vault", "secret": "агент культа"}],
}


def create(client, admin, title="Мир"):
    r = client.post("/api/author/projects", json={"title": title, "budget_usd": 5}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def put_plan(settings, project_id, plan):
    async def go():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as s:
                from app.db.models import AuthorProject

                project = await s.get(AuthorProject, project_id)
                (await s.get(CampaignSecret, project.workspace_campaign_id)).plot = plan
                await s.commit()
        finally:
            await engine.dispose()

    asyncio.run(go())


def count(settings, table):
    async def go():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as s:
                return await s.scalar(select(func.count()).select_from(table))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def second_admin(client, root):
    r = client.post("/api/admin/users", json={"name": "Other", "password": "secret1"}, headers=root)
    assert r.status_code == 201, r.text
    return login(client, "Other", "secret1")


def test_access_projects_summary_full_and_hidden_workspace(client, admin, root, settings):
    project = create(client, admin)
    pid = project["id"]
    other = second_admin(client, root)
    assert client.get("/api/author/projects", headers=other).json() == []
    for method, path in (("get", f"/api/author/projects/{pid}"), ("get", f"/api/author/projects/{pid}/jobs")):
        assert getattr(client, method)(path, headers=other).status_code == 404  # чужой admin не узнаёт о проекте
    assert client.get(f"/api/author/projects/{pid}").status_code == 401
    assert [p["id"] for p in client.get("/api/author/projects", headers=admin).json()] == [pid]

    put_plan(settings, pid, PLAN)
    summary = client.get(f"/api/author/projects/{pid}", headers=admin).json()
    assert summary["preparation"]["content"] is None
    assert "traitor" not in json.dumps(summary) and "vault" not in json.dumps(summary)
    full = client.get(f"/api/author/projects/{pid}?view=full", headers=admin).json()
    assert "npc_traitor" in json.dumps(full["preparation"]["content"])
    assert client.get("/api/campaigns", headers=admin).json() == []  # рабочий мир не в игровом списке


def test_prepare_is_accepted_idempotent_stale_is_409_and_get_does_not_start_work(client, admin, settings):
    project = create(client, admin)
    pid, rev = project["id"], project["draft_revision"]
    body = {"stage": "lore", "expected_revision": rev, "request_key": "k1"}
    first = client.post(f"/api/author/projects/{pid}/prepare", json=body, headers=admin)
    assert first.status_code == 202 and first.json()["status"] == "queued"
    again = client.post(f"/api/author/projects/{pid}/prepare", json=body, headers=admin)
    assert again.json()["job_id"] == first.json()["job_id"]
    stale = client.post(
        f"/api/author/projects/{pid}/prepare",
        json={**body, "request_key": "k2", "expected_revision": rev + 9},
        headers=admin,
    )
    assert stale.status_code == 409
    before = count(settings, AuthorJob)
    jobs = client.get(f"/api/author/projects/{pid}/jobs", headers=admin).json()
    client.get(f"/api/author/projects/{pid}?view=full", headers=admin)
    assert [j["id"] for j in jobs] == [first.json()["job_id"]] and "result" not in jobs[0]
    assert count(settings, AuthorJob) == before and count(settings, LlmCall) == 0


def test_edits_preview_apply_and_stale(client, admin, settings):
    project = create(client, admin)
    pid = project["id"]
    put_plan(settings, pid, PLAN)
    rev = client.get(f"/api/author/projects/{pid}", headers=admin).json()["project"]["draft_revision"]
    edit = {"op": "update_plot_object", "ref": "npc_traitor", "fields": {"name": "Лжец"}}

    class Llm:
        async def complete(self, messages, **kw):
            return LLMReply(text=json.dumps({"operations": [edit]}), model="m", cost=0.001, cost_known=True)

    client.app.state.master.llm = Llm()
    preview = client.post(
        f"/api/author/projects/{pid}/edits/preview",
        json={"instruction": "переименуй", "base_revision": rev},
        headers=admin,
    )
    assert preview.status_code == 200 and preview.json()["patch"]["operations"][0]["ref"] == "npc_traitor"
    unchanged = client.get(f"/api/author/projects/{pid}?view=full", headers=admin).json()
    assert unchanged["project"]["draft_revision"] == rev  # предложение ничего не меняет
    applied = client.post(
        f"/api/author/projects/{pid}/edits",
        json={"patch": preview.json()["patch"], "expected_revision": rev, "request_key": "e1"},
        headers=admin,
    )
    assert applied.status_code == 200 and applied.json()["applied"] is True
    stale = client.post(
        f"/api/author/projects/{pid}/edits",
        json={"patch": preview.json()["patch"], "expected_revision": rev, "request_key": "e2"},
        headers=admin,
    )
    assert stale.status_code == 409
    old = client.post(
        f"/api/author/projects/{pid}/edits/preview", json={"instruction": "x", "base_revision": rev}, headers=admin
    )
    assert old.status_code == 409
    bad = client.post(
        f"/api/author/projects/{pid}/edits",
        json={
            "patch": {"operations": [{"op": "fight", "who": "x"}]},
            "expected_revision": rev + 1,
            "request_key": "e3",
        },
        headers=admin,
    )
    assert bad.status_code == 422


def test_validate_redacts_spoilers_publish_blocked_and_unknown_map(client, admin, settings):
    project = create(client, admin)
    pid = project["id"]
    put_plan(settings, pid, PLAN)
    rev = client.get(f"/api/author/projects/{pid}", headers=admin).json()["project"]["draft_revision"]
    summary = client.post(f"/api/author/projects/{pid}/validate", headers=admin)
    assert summary.status_code == 200
    errors = summary.json()["errors"]
    assert errors and all(e["object_ref"] is None and e["related_refs"] == [] for e in errors)
    assert "vault" not in summary.text and "traitor" not in summary.text
    full = client.post(f"/api/author/projects/{pid}/validate?view=full", headers=admin)
    assert any(e["object_ref"] == "loc_secret_vault" for e in full.json()["errors"])
    blocked = client.post(
        f"/api/author/projects/{pid}/publish", json={"expected_revision": rev, "request_key": "p1"}, headers=admin
    )
    assert blocked.status_code == 409 and blocked.json()["detail"] == "publication_blocked"
    assert "bundle" not in blocked.text
    assert client.get(f"/api/author/projects/{pid}/maps/loc_nothing", headers=admin).status_code == 404


def test_rename_project_changes_title_only_and_is_owner_only(client, admin, root):
    project = create(client, admin, title="Старое имя")
    url = f"/api/author/projects/{project['id']}"
    r = client.patch(url, json={"title": "  Новое имя  "}, headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Новое имя"
    assert r.json()["draft_revision"] == project["draft_revision"]  # metadata, not draft content
    assert client.get(url, headers=admin).json()["project"]["title"] == "Новое имя"
    assert [p["title"] for p in client.get("/api/author/projects", headers=admin).json()] == ["Новое имя"]

    assert client.patch(url, json={"title": "   "}, headers=admin).status_code == 422
    assert client.patch(url, json={"title": "x" * 129}, headers=admin).status_code == 422
    other = second_admin(client, root)
    assert client.patch(url, json={"title": "Чужое"}, headers=other).status_code in (403, 404)
