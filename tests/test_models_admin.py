"""Профили ролей и модели ИИ: настройка и проверка связи у Admin и Super Admin, смена модели мастера кампании."""

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import ScriptedLLM
from app.main import create_app
from tests.conftest import login
from tests.game import ok


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


def test_providers_show_only_whether_key_is_set(client, admin, player, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert client.get("/api/admin/providers", headers=player).status_code == 403
    r = client.get("/api/admin/providers", headers=admin)
    assert "sk-secret" not in r.text
    p = {x["id"]: x for x in r.json()}
    assert p["claude"]["key_set"] is True and p["gemini"]["key_set"] is False and p["local"]["key_set"] is None


def test_active_provider_switch_applies_without_restart(client, admin, player, monkeypatch, tmp_path):
    from app import config
    from app.agents.llm import decide_model_for, model_for, parser_model_for

    monkeypatch.setattr(config, "ROOT", tmp_path)  # .env пишется во временную папку
    monkeypatch.setenv("LLM_PROVIDER", config.settings.llm_provider)  # вернётся после теста
    saved = {k: getattr(config.settings, k) for k in config.LLM_FIELDS}
    try:
        url = "/api/admin/providers/active"
        assert client.patch(url, json={"provider": "claude"}, headers=player).status_code == 403
        assert client.patch(url, json={"provider": "gemini\nJWT_SECRET=x"}, headers=admin).status_code == 409
        ok(client.patch(url, json={"provider": "claude"}, headers=admin))
        # модули держат тот же объект settings: смена видна сразу, без перезапуска
        assert model_for() == config.settings.claude_main_model
        assert decide_model_for() == parser_model_for() == config.settings.claude_technical_model
        assert "LLM_PROVIDER=claude" in (tmp_path / ".env").read_text(encoding="utf-8")
        listed = ok(client.get("/api/admin/providers", headers=admin))
        assert [x["id"] for x in listed if x["is_active"]] == ["claude"]
    finally:
        for k, v in saved.items():
            object.__setattr__(config.settings, k, v)


def test_decide_model_follows_env():
    from app import config
    from app.agents.llm import decide_model_for, model_for, parser_model_for

    assert config.settings.decide_model == "technical"  # по умолчанию решение хода — на технической модели
    assert decide_model_for() == parser_model_for()
    object.__setattr__(config.settings, "decide_model", "main")
    try:
        assert decide_model_for() == model_for()
    finally:
        object.__setattr__(config.settings, "decide_model", "technical")


def test_check_provider_without_key(client, admin, llm, monkeypatch):
    # без ключа на сервере запрос к провайдеру не уходит
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sent = len(llm.requests)
    r = ok(client.post("/api/admin/providers/check", json={"provider": "claude"}, headers=admin))
    assert not r["ok"] and "ANTHROPIC_API_KEY" in r["error"] and len(llm.requests) == sent
