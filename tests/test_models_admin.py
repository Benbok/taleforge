"""Профили ролей и модели ИИ: настройка и проверка связи у Admin и Super Admin, смена модели мастера кампании."""

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import LLMError, ScriptedLLM
from app.main import create_app
from tests.conftest import login
from tests.game import ok
from tests.test_api import make_campaign


@pytest.fixture
def llm():
    return ScriptedLLM([])


@pytest.fixture
def client(settings, llm):
    with TestClient(create_app(settings, llm=llm)) as c:
        yield c


@pytest.fixture
def player(client):
    r = ok(client.post("/api/auth/signup", json={"name": "Гимли", "password": "pass123"}))
    return {"Authorization": f"Bearer {r['token']}"}


def lm_profile(client, headers, **kw):
    body = {"name": "Qwen локально", "provider": "local", "model": "qwen2.5-14b", "api_base": "http://pc:1234/v1", **kw}
    r = client.post("/api/admin/models", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_profile_for_every_role(client, root, admin, player):
    me = ok(client.get("/api/me/profile", headers=player))
    assert me["user"]["name"] == "Гимли" and not me["can_manage_models"] and not me["can_manage_users"]
    assert "llm_spend_usd" not in me["stats"]
    a = ok(client.get("/api/me/profile", headers=admin))
    assert a["can_manage_models"] and not a["can_manage_users"] and a["stats"]["llm_spend_usd"] == 0
    r = ok(client.get("/api/me/profile", headers=root))
    assert r["can_manage_models"] and r["can_manage_users"]


def test_rename_and_password(client, player):
    assert ok(client.patch("/api/me", json={"name": "Гимли сын Глоина"}, headers=player))["name"] == "Гимли сын Глоина"
    r = client.post("/api/me/password", json={"old_password": "wrong", "new_password": "newpass1"}, headers=player)
    assert r.status_code == 409
    r = client.post("/api/me/password", json={"old_password": "pass123", "new_password": "1"}, headers=player)
    assert r.status_code == 422 and r.json()["detail"].startswith("Новый пароль")
    r = client.post("/api/me/password", json={"old_password": "pass123", "new_password": "newpass1"}, headers=player)
    assert r.status_code == 204
    login(client, "Гимли сын Глоина", "newpass1")


def test_superadmin_changes_roles(client, root, admin, player):
    users = {u["name"]: u for u in ok(client.get("/api/admin/users", headers=root))}
    gimli = users["Гимли"]["id"]
    assert client.patch(f"/api/admin/users/{gimli}", json={"platform_role": "admin"}, headers=admin).status_code == 403
    assert (
        ok(client.patch(f"/api/admin/users/{gimli}", json={"platform_role": "admin"}, headers=root))["platform_role"]
        == "admin"
    )
    me = users["root"]["id"]
    assert client.patch(f"/api/admin/users/{me}", json={"platform_role": "admin"}, headers=root).status_code == 409


def test_superadmin_deletes_user(client, root, admin, player):
    users = {u["name"]: u for u in ok(client.get("/api/admin/users", headers=root))}
    gimli = users["Гимли"]["id"]
    root_id = users["root"]["id"]

    assert client.delete(f"/api/admin/users/{gimli}", headers=admin).status_code == 403
    assert client.delete(f"/api/admin/users/{root_id}", headers=root).status_code == 409
    assert client.delete(f"/api/admin/users/{gimli}", headers=root).status_code == 204
    assert "Гимли" not in {u["name"] for u in ok(client.get("/api/admin/users", headers=root))}
    assert client.post("/api/auth/login", json={"name": "Гимли", "password": "pass123"}).status_code == 401


def test_providers_show_only_whether_key_is_set(client, admin, player, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert client.get("/api/admin/providers", headers=player).status_code == 403
    r = client.get("/api/admin/providers", headers=admin)
    assert "sk-secret" not in r.text
    p = {x["id"]: x for x in r.json()}
    assert p["claude"]["key_set"] is True and p["gemini"]["key_set"] is False and p["local"]["key_set"] is None


def test_model_profiles_crud_and_default(client, root, admin, player):
    assert client.get("/api/admin/models", headers=player).status_code == 403
    r = client.post("/api/admin/models", json={"name": "Gemini", "provider": "gemini"}, headers=admin)
    assert r.status_code == 409  # у Gemini нужна модель
    p = lm_profile(client, admin)
    assert p["resolved_model"] == "lm_studio/qwen2.5-14b" and p["created_by_name"] == "Arty"
    # модель по умолчанию назначает только Super Admin
    assert client.patch(f"/api/admin/models/{p['id']}", json={"is_default": True}, headers=admin).status_code == 403
    assert ok(client.patch(f"/api/admin/models/{p['id']}", json={"is_default": True}, headers=root))["is_default"]
    c2 = ok(
        client.post("/api/admin/models", json={"name": "Opus", "provider": "claude", "is_default": True}, headers=root),
        201,
    )
    listed = ok(client.get("/api/admin/models", headers=admin))
    assert [x["name"] for x in listed if x["is_default"]] == ["Opus"] and c2["resolved_model"]
    # смена провайдера сбрасывает адрес LM Studio
    moved = ok(
        client.patch(
            f"/api/admin/models/{p['id']}", json={"provider": "gemini", "model": "gemini-2.5-pro"}, headers=admin
        )
    )
    assert moved["api_base"] is None and moved["resolved_model"] == "gemini/gemini-2.5-pro"
    assert client.delete(f"/api/admin/models/{c2['id']}", headers=admin).status_code == 403
    assert client.delete(f"/api/admin/models/{p['id']}", headers=admin).status_code == 204


def test_check_model(client, admin, llm, monkeypatch):
    p = lm_profile(client, admin)
    llm.replies = [{"text": "готов"}]
    checked = ok(client.post(f"/api/admin/models/{p['id']}/check", headers=admin))
    assert checked["last_check"]["ok"] and checked["last_check"]["reply"] == "готов"
    assert llm.requests[-1]["model"] == "lm_studio/qwen2.5-14b"
    assert llm.requests[-1]["api_base"] == "http://pc:1234/v1"

    def down(messages, tools):
        raise LLMError("APIConnectionError: connection refused")

    llm.replies = [down]
    failed = ok(client.post(f"/api/admin/models/{p['id']}/check", headers=admin))
    assert not failed["last_check"]["ok"] and "нет связи с сервером модели" in failed["last_check"]["error"]
    # без ключа на сервере запрос к провайдеру не уходит
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sent = len(llm.requests)
    r = ok(client.post("/api/admin/models/check", json={"provider": "claude"}, headers=admin))
    assert not r["ok"] and "ANTHROPIC_API_KEY" in r["error"] and len(llm.requests) == sent


def test_campaign_master_uses_profiles(client, root, admin, player):
    p = lm_profile(client, admin, temperature=0.5)
    c = make_campaign(client, admin, master={"type": "agent", "model_profile_id": p["id"]})
    m = ok(client.get(f"/api/campaigns/{c['id']}/master-model", headers=admin))
    assert m["provider"] == "local" and m["api_base"] == "http://pc:1234/v1" and m["temperature"] == 0.5
    assert m["model_profile_name"] == "Qwen локально"
    # без выбора — профиль по умолчанию, а без него Claude
    plain = make_campaign(client, admin, master={"type": "agent"})
    assert ok(client.get(f"/api/campaigns/{plain['id']}/master-model", headers=admin))["provider"] == "claude"
    ok(client.patch(f"/api/admin/models/{p['id']}", json={"is_default": True}, headers=root))
    dflt = make_campaign(client, admin, master={"type": "agent"})
    assert ok(client.get(f"/api/campaigns/{dflt['id']}/master-model", headers=admin))["model_profile_id"] == p["id"]
    # владелец меняет модель у идущей кампании
    opus = ok(client.post("/api/admin/models", json={"name": "Opus", "provider": "claude"}, headers=admin), 201)
    url = f"/api/campaigns/{c['id']}/master-model"
    changed = ok(client.put(url, json={"model_profile_id": opus["id"]}, headers=admin))
    assert changed["provider"] == "claude" and changed["api_base"] is None and changed["model_profile_name"] == "Opus"
    assert client.put(url, json={}, headers=admin).status_code == 409
    own = make_campaign(client, admin, master={"type": "owner"})
    assert client.get(f"/api/campaigns/{own['id']}/master-model", headers=admin).status_code == 409
