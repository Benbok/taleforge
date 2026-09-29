# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Админка (этап 7, часть 6): загрузка пакета архивом и расходы на модели."""

import io
import zipfile
from pathlib import Path

from app.db.models import LlmCall
from tests.conftest import login
from tests.game import ok, run
from tests.test_api import make_campaign

CONTENT = Path(__file__).resolve().parents[1] / "content"
ZIP = {"Content-Type": "application/zip"}


def _zip(root: Path, prefix: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in root.rglob("*"):
            if p.is_file():
                z.write(p, prefix + str(p.relative_to(root)))
    return buf.getvalue()


def test_pack_upload_checks_then_imports(client, admin):
    data = _zip(CONTENT / "dnd5e-srd", "dnd5e-srd/")
    dry = ok(client.post("/api/admin/packs?dry_run=true", content=data, headers={**admin, **ZIP}))
    assert dry["ok"] and dry["pack_id"] == "dnd5e-srd" and dry["imported"] == [] and not dry["errors"]
    assert ok(client.get("/api/packs", headers=admin)) == []
    done = ok(client.post("/api/admin/packs", content=data, headers={**admin, **ZIP}))
    assert done["imported"][0]["state"] == "imported"
    assert [p["id"] for p in ok(client.get("/api/packs", headers=admin))] == ["dnd5e-srd"]
    again = ok(client.post("/api/admin/packs", content=data, headers={**admin, **ZIP}))
    assert again["imported"][0]["state"] == "unchanged"


def test_pack_upload_rejects_bad_archives(client, admin, root):
    r = client.post("/api/admin/packs", content=b"not a zip", headers={**admin, **ZIP})
    assert r.status_code == 400 and r.json()["detail"] == "это не zip-архив"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.yaml", "x: 1")
    r = client.post("/api/admin/packs", content=buf.getvalue(), headers={**admin, **ZIP})
    assert r.status_code == 400 and "недопустимый путь" in r.json()["detail"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "hi")
    r = client.post("/api/admin/packs", content=buf.getvalue(), headers={**admin, **ZIP})
    assert r.status_code == 400 and "нет pack.yaml" in r.json()["detail"]
    # игрок пакеты не грузит
    body = {"name": "Pl", "password": "secret1", "platform_role": "player"}
    ok(client.post("/api/admin/users", json=body, headers=root), 201)
    pl = login(client, "Pl", "secret1")
    assert client.post("/api/admin/packs", content=b"x", headers={**pl, **ZIP}).status_code == 403


def test_spend_by_scope(client, admin, root, settings):
    mine = make_campaign(client, admin, spend_limit_usd=1.0)
    ok(client.post("/api/admin/users", json={"name": "Other", "password": "secret1"}, headers=root), 201)
    other_admin = login(client, "Other", "secret1")
    theirs = make_campaign(client, other_admin)

    async def seed(s):
        rows = [(mine["id"], 0.25, "m-a"), (mine["id"], 0.5, "m-b"), (theirs["id"], 2.0, "m-a"), (None, 0.01, "m-a")]
        for cid, cost, model in rows:
            s.add(LlmCall(campaign_id=cid, purpose="narrate", model=model, tokens_in=100, tokens_out=10, cost=cost))
        await s.commit()

    run(settings, seed)
    own = ok(client.get("/api/admin/spend", headers=admin))
    assert own["scope"] == "own" and own["total"]["cost"] == 0.75 and own["total"]["calls"] == 2
    (row,) = own["by_campaign"]
    assert row["id"] == mine["id"] and row["limit"] == 1.0 and row["spent_total"] == 0.75
    assert [m["model"] for m in own["by_model"]] == ["m-b", "m-a"]
    assert len(own["by_day"]) == 1

    everything = ok(client.get("/api/admin/spend", headers=root))
    assert everything["scope"] == "all" and round(everything["total"]["cost"], 2) == 2.76
    names = {r["id"]: r["name"] for r in everything["by_campaign"]}
    assert names[""] == "Вне кампаний: проверка моделей"
