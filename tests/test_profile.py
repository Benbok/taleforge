"""Профиль игрока: быстрая регистрация, приглашение после входа, библиотека героев, готовые герои, место владельца."""

import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.game import FIGHTER, import_base, ok
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


def test_library_hero_copied_into_campaign(client, admin, base):
    h = signup(client, "Гимли")
    other = signup(client, "Леголас")
    opts = ok(client.get("/api/me/character-options", headers=h))
    assert len(opts["classes"]) == 12
    hero = ok(client.post("/api/me/characters", json=FIGHTER, headers=h), 201)
    assert hero["errors"] == [] and hero["class_name"] == "Воин"
    assert client.get(f"/api/me/characters/{hero['id']}", headers=other).status_code == 404
    assert ok(client.get("/api/me/characters", headers=other)) == []

    rolled = ok(client.post("/api/me/characters", json={"name": "Кубик"}, headers=h), 201)
    ok(client.post(f"/api/me/characters/{rolled['id']}/roll-abilities", headers=h))
    assert client.post(f"/api/me/characters/{rolled['id']}/roll-abilities", headers=h).status_code == 409

    c = make_campaign(client, admin, players=2, creation_rules={"review": "auto"})
    ok(client.post(f"/api/invites/{invite(client, admin, c['id'])['token']}/accept", headers=h))
    copy = ok(client.post(f"/api/campaigns/{c['id']}/characters/from-library/{hero['id']}", headers=h), 201)
    assert copy["status"] == "draft" and copy["errors"] == [] and copy["sheet"]["source_library_id"] == hero["id"]
    assert copy["id"] != hero["id"]
    res = ok(client.post(f"/api/campaigns/{c['id']}/characters/{copy['id']}/submit", headers=h))
    assert res["status"] == "approved"
    # копия в кампании живёт отдельно от героя в профиле
    ok(client.put(f"/api/campaigns/{c['id']}/characters/{copy['id']}", json={"name": "Бран Седой"}, headers=h))
    assert ok(client.get(f"/api/me/characters/{hero['id']}", headers=h))["name"] == "Бран"
    ok(client.put(f"/api/me/characters/{hero['id']}", json={"public_bio": "Другая история"}, headers=h))
    camp = ok(client.get(f"/api/campaigns/{c['id']}/characters/{copy['id']}", headers=h))
    assert camp["public_bio"] == FIGHTER["public_bio"] and camp["name"] == "Бран Седой"
    # чужого героя в кампанию не взять
    r = client.post(f"/api/campaigns/{c['id']}/characters/from-library/{hero['id']}", headers=other)
    assert r.status_code == 404


def test_premade_hero_chosen_by_player(client, admin, base):
    c = make_campaign(client, admin, players=2)
    pre = ok(client.post(f"/api/campaigns/{c['id']}/premades", json=FIGHTER, headers=admin), 201)
    assert pre["status"] == "premade" and pre["errors"] == [] and pre["seat_id"] is None
    inv = invite(client, admin, c["id"])
    h, h2 = signup(client, "Гимли"), signup(client, "Леголас")
    for x in (h, h2):
        ok(client.post(f"/api/invites/{inv['token']}/accept", headers=x))
    assert client.post(f"/api/campaigns/{c['id']}/premades", json=FIGHTER, headers=h).status_code == 403

    seen = ok(client.get(f"/api/campaigns/{c['id']}/characters", headers=h))
    assert [x["status"] for x in seen] == ["premade"] and seen[0]["private_backstory"] == FIGHTER["private_backstory"]

    # начатый черновик уступает место выбранному герою
    ok(client.post(f"/api/campaigns/{c['id']}/characters", json={"name": "Набросок"}, headers=h), 201)
    got = ok(client.post(f"/api/campaigns/{c['id']}/characters/{pre['id']}/claim", headers=h))
    assert got["status"] == "approved" and got["resources"]["hp"] == 12 and got["inventory"]
    assert client.post(f"/api/campaigns/{c['id']}/characters/{pre['id']}/claim", headers=h2).status_code == 409
    mine = [x for x in ok(client.get(f"/api/campaigns/{c['id']}/characters", headers=h)) if x["status"] != "premade"]
    assert [x["name"] for x in mine] == ["Бран"]
    r = client.put(f"/api/campaigns/{c['id']}/premades/{pre['id']}", json={"name": "x"}, headers=admin)
    assert r.status_code == 409
