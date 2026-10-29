"""Профиль игрока: быстрая регистрация, приглашение после входа, библиотека героев, готовые герои, место владельца."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.game import import_base, ok
from tests.test_api import invite, make_campaign


@pytest.fixture
def base(settings):
    import_base(settings)


def signup(client, name, password="pass123"):
    r = ok(client.post("/api/auth/signup", json={"name": name, "password": password}))
    return {"Authorization": f"Bearer {r['token']}"}


def test_signup_and_russian_errors(client):
    r = client.post("/api/auth/signup", json={"name": "Гимли", "password": "123"})
    assert r.status_code == 422 and r.json()["detail"] == "Пароль: не короче 6 символов"
    r = client.post("/api/auth/signup", json={"name": "Г", "password": "pass123"})
    assert r.json()["detail"] == "Имя: не короче 2 символов"
    h = signup(client, "Гимли")
    assert ok(client.get("/api/auth/me", headers=h))["platform_role"] == "player"
    assert client.post("/api/auth/signup", json={"name": "Гимли", "password": "pass123"}).status_code == 409
    # игрок без приглашения кампаний не видит и создавать их не может
    assert ok(client.get("/api/campaigns", headers=h)) == []
    assert client.post("/api/campaigns", json={"name": "x"}, headers=h).status_code == 403


def test_signup_can_be_closed(settings):
    closed = dataclasses.replace(settings, open_signup=False)
    with TestClient(create_app(closed)) as c:
        assert c.post("/api/auth/signup", json={"name": "Гимли", "password": "pass123"}).status_code == 403


def test_invite_accepted_after_signup(client, admin):
    c = make_campaign(client, admin, players=2)
    inv = invite(client, admin, c["id"])
    h = signup(client, "Гимли")
    joined = ok(client.post(f"/api/invites/{inv['token']}/accept", headers=h))
    assert joined["my_role"] == "player" and joined["my_seat_id"]


def test_owner_takes_player_seat(client, admin):
    c = make_campaign(client, admin, players=2, owner_plays=True)
    assert c["my_role"] == "player" and c["my_seat_id"]
    own = make_campaign(client, admin, players=2, master={"type": "owner"}, owner_plays=True)
    assert own["my_role"] == "master"
    later = make_campaign(client, admin, players=2)
    assert later["my_role"] is None
    took = ok(client.post(f"/api/campaigns/{later['id']}/seats/take", headers=admin))
    assert took["my_role"] == "player"
    assert client.post(f"/api/campaigns/{later['id']}/seats/take", headers=admin).status_code == 409
