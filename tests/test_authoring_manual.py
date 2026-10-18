import asyncio

from sqlalchemy import func, select

from app.content.yaml_io import load_file
from app.db.models import LlmCall
from app.db.session import make_engine, make_sessionmaker
from tests.game import BASE, import_base
from tests.test_plan import good_plan


def project(client, admin, settings):
    import_base(settings)
    pack = load_file(BASE / "pack.yaml")
    r = client.post(
        "/api/author/projects",
        json={
            "title": "Ручной мир",
            "pack_id": str(pack["id"]),
            "pack_version": str(pack["version"]),
            "brief": {"length": "short"},
        },
        headers=admin,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def view(client, admin, pid, mode="summary"):
    return client.get(f"/api/author/projects/{pid}?view={mode}", headers=admin).json()


def status(client, admin, pid):
    return {s["stage"]: s["status"] for s in view(client, admin, pid)["preparation"]["stages"]}


def llm_calls(settings):
    async def go():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as s:
                return await s.scalar(select(func.count()).select_from(LlmCall))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_lore_written_by_hand_counts_as_done_without_any_model_call(client, admin, settings):
    pid = project(client, admin, settings)
    rev = view(client, admin, pid)["project"]["draft_revision"]
    ops = [
        {
            "op": "set_lore",
            "fields": {"overview": "Мир, написанный вручную.", "history": [{"when": "давно", "event": "война"}]},
        }
    ]
    r = client.post(
        f"/api/author/projects/{pid}/edits",
        json={"patch": {"operations": ops}, "expected_revision": rev, "request_key": "lore-hand"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert status(client, admin, pid)["lore"] == "manual"
    assert view(client, admin, pid, "full")["preparation"]["content"]["setting"]["lore"]["overview"].startswith("Мир")
    assert llm_calls(settings) == 0


def test_tasks_for_outside_models_are_read_only(client, admin, settings):
    pid = project(client, admin, settings)
    rev = view(client, admin, pid)["project"]["draft_revision"]
    for stage, key in (("lore", "overview"), ("plot", "locations")):
        r = client.get(f"/api/author/projects/{pid}/tasks/{stage}", headers=admin)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["system"] and body["user"] and key in body["schema"]["properties"]
    assert client.get(f"/api/author/projects/{pid}/tasks/maps", headers=admin).status_code == 422
    assert view(client, admin, pid)["project"]["draft_revision"] == rev
    assert llm_calls(settings) == 0


def test_imported_plot_is_checked_and_unlocks_geography(client, admin, settings):
    pid = project(client, admin, settings)
    rev = view(client, admin, pid)["project"]["draft_revision"]
    broken = good_plan()
    broken.pop("title")
    r = client.post(
        f"/api/author/projects/{pid}/plot/import",
        json={"plan": broken, "expected_revision": rev, "request_key": "imp-bad"},
        headers=admin,
    )
    assert r.status_code == 409 and r.json()["errors"]
    assert status(client, admin, pid)["plot"] == "not_requested"
    blocked = client.post(
        f"/api/author/projects/{pid}/prepare",
        json={"stage": "geography", "expected_revision": rev, "request_key": "g0"},
        headers=admin,
    )
    assert blocked.status_code == 409 and "plot" in blocked.json()["detail"]

    r = client.post(
        f"/api/author/projects/{pid}/plot/import",
        json={"plan": good_plan(), "expected_revision": rev, "request_key": "imp-1"},
        headers=admin,
    )
    assert r.status_code == 200, r.text
    assert status(client, admin, pid)["plot"] == "manual"
    plan = view(client, admin, pid, "full")["preparation"]["content"]["plot"]
    assert plan["title"] == good_plan()["title"] and plan["locations"]
    rev = view(client, admin, pid)["project"]["draft_revision"]
    ok = client.post(
        f"/api/author/projects/{pid}/prepare",
        json={"stage": "geography", "expected_revision": rev, "request_key": "g1"},
        headers=admin,
    )
    assert ok.status_code == 202, ok.text
    text = client.post(
        f"/api/author/projects/{pid}/edits",
        json={
            "patch": {"operations": [{"op": "set_plot_text", "fields": {"tagline": "Своими руками"}}]},
            "expected_revision": rev,
            "request_key": "t1",
        },
        headers=admin,
    )
    assert text.status_code == 200, text.text
    assert view(client, admin, pid, "full")["preparation"]["content"]["plot"]["tagline"] == "Своими руками"
    assert llm_calls(settings) == 0
