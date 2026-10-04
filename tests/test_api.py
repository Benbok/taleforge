from datetime import UTC, datetime, timedelta

from tests.conftest import login


def make_campaign(client, admin, **kw):
    # в тестах владелец не садится за стол сам, чтобы места достались приглашённым
    body = {"name": "Тест", "master": {"type": "agent", "provider": "claude", "model": "x"}, "owner_plays": False, **kw}
    r = client.post("/api/campaigns", json=body, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def invite(client, admin, cid, **kw):
    r = client.post(f"/api/campaigns/{cid}/invites", json=kw, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def register(client, token, name):
    r = client.post(f"/api/auth/register/{token}", json={"name": name, "password": "pass123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_health_and_auth(client, root):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=root).json()["platform_role"] == "super_admin"
    assert client.post("/api/auth/login", json={"name": "root", "password": "nope"}).status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_only_superadmin_creates_users(client, admin):
    r = client.post("/api/admin/users", json={"name": "Other", "password": "secret1"}, headers=admin)
    assert r.status_code == 403


def test_create_campaign_seats_and_party_size(client, admin):
    c = make_campaign(client, admin)
    assert c["party_size_recommended"] == 4
    assert [s["role"] for s in c["seats"]] == ["master"] + ["player"] * 4
    assert (
        c["seats"][0]["occupant_type"] == "agent" and c["seats"][0]["agent_provider"] == "env"
    )  # провайдер и модели — из .env сервера
    assert c["settings"]["turn_timeout_sec"] == 300 and c["settings"]["spend_limit_usd"] is None
    c2 = make_campaign(client, admin, players=6, master={"type": "owner"})
    assert len(c2["seats"]) == 7 and c2["my_role"] == "master"
    r = client.post("/api/campaigns", json={"name": "x", "players": 7}, headers=admin)
    assert r.status_code == 422
    assert client.get("/api/party-size?difficulty=hard", headers=admin).json() == {"min": 3, "recommended": 4, "max": 6}


def test_player_cannot_create_campaign(client, admin):
    c = make_campaign(client, admin)
    p = register(client, invite(client, admin, c["id"])["token"], "Боромир")
    assert client.post("/api/campaigns", json={"name": "x"}, headers=p).status_code == 403


def test_invite_flow_and_visibility(client, admin):
    c = make_campaign(client, admin, players=2)
    inv = invite(client, admin, c["id"], max_uses=2)
    assert inv["url"] == f"http://play.test/invite/{inv['token']}"
    preview = client.get(f"/api/invites/{inv['token']}").json()
    assert preview["valid"] and preview["free_seats"] == 2 and preview["campaign_name"] == "Тест"

    p1 = register(client, inv["token"], "Арагорн")
    p2 = register(client, inv["token"], "Гимли")
    assert client.get(f"/api/invites/{inv['token']}").json()["valid"] is False  # мест и использований не осталось
    r = client.post(f"/api/auth/register/{inv['token']}", json={"name": "Леголас", "password": "pass123"})
    assert r.status_code == 409

    mine = client.get("/api/campaigns", headers=p1).json()
    assert [x["id"] for x in mine] == [c["id"]] and mine[0]["my_role"] == "player"
    # Игрок не приглашает, не исключает, не видит тайн
    assert client.post(f"/api/campaigns/{c['id']}/invites", json={}, headers=p1).status_code == 403
    assert client.get(f"/api/campaigns/{c['id']}/secrets", headers=p1).status_code == 404
    seat2 = next(
        s for s in client.get(f"/api/campaigns/{c['id']}", headers=p2).json()["seats"] if s["user_name"] == "Гимли"
    )
    assert client.delete(f"/api/campaigns/{c['id']}/seats/{seat2['id']}/occupant", headers=p1).status_code == 403
    # Владелец исключает — место освобождается, кампания игроку больше не видна
    r = client.delete(f"/api/campaigns/{c['id']}/seats/{seat2['id']}/occupant", headers=admin)
    assert r.status_code == 200
    assert client.get(f"/api/campaigns/{c['id']}", headers=p2).status_code == 404


def test_secrets_only_for_master_seat(client, admin):
    agent_run = make_campaign(client, admin)
    # Владелец при ИИ-мастере скрытого не видит (раздел 2)
    assert client.get(f"/api/campaigns/{agent_run['id']}/secrets", headers=admin).status_code == 404
    own = make_campaign(client, admin, master={"type": "owner"})
    r = client.put(f"/api/campaigns/{own['id']}/secrets", json={"plot": {"twist": "x"}}, headers=admin)
    assert r.status_code == 200
    assert client.get(f"/api/campaigns/{own['id']}/secrets", headers=admin).json()["plot"] == {"twist": "x"}


def test_invite_expiry_and_revoke(client, admin):
    c = make_campaign(client, admin)
    inv = invite(client, admin, c["id"])
    assert client.delete(f"/api/campaigns/{c['id']}/invites/{inv['token']}", headers=admin).status_code == 204
    assert client.get(f"/api/invites/{inv['token']}").json()["problem"] == "приглашение недействительно"
    assert client.get("/api/invites/nope").json()["valid"] is False


def test_invite_expired(client, admin, settings):
    import asyncio

    from app.db.models import Invite
    from app.db.session import make_engine, make_sessionmaker

    c = make_campaign(client, admin)
    inv = invite(client, admin, c["id"])

    async def expire():
        engine = make_engine(settings.database_url)
        async with make_sessionmaker(engine)() as s:
            (await s.get(Invite, inv["token"])).expires_at = datetime.now(UTC) - timedelta(minutes=1)
            await s.commit()
        await engine.dispose()

    asyncio.run(expire())
    assert client.get(f"/api/invites/{inv['token']}").json()["problem"] == "срок приглашения истёк"


def test_patch_and_delete(client, admin):
    c = make_campaign(client, admin)
    r = client.patch(f"/api/campaigns/{c['id']}", json={"name": "Новое", "spend_limit_usd": 5}, headers=admin)
    assert r.json()["name"] == "Новое" and r.json()["settings"]["spend_limit_usd"] == 5
    p = register(client, invite(client, admin, c["id"])["token"], "Фродо")
    assert client.patch(f"/api/campaigns/{c['id']}", json={"name": "x"}, headers=p).status_code == 403
    assert client.delete(f"/api/campaigns/{c['id']}", headers=p).status_code == 403
    assert client.delete(f"/api/campaigns/{c['id']}", headers=admin).status_code == 204
    assert client.get(f"/api/campaigns/{c['id']}", headers=admin).status_code == 404


def test_other_admin_cannot_see_campaign(client, admin, root):
    c = make_campaign(client, admin)
    client.post("/api/admin/users", json={"name": "Other", "password": "secret1"}, headers=root)
    other = login(client, "Other", "secret1")
    assert client.get(f"/api/campaigns/{c['id']}", headers=other).status_code == 404
    assert client.get("/api/campaigns", headers=other).json() == []


def test_session_control(client, admin):
    c = make_campaign(client, admin)
    p = register(client, invite(client, admin, c["id"])["token"], "Сэм")
    assert client.post(f"/api/campaigns/{c['id']}/session/start", headers=p).status_code == 403
    assert client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin).json()["status"] == "active"
    assert client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin).status_code == 409
    assert client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin).json()["status"] == "paused"
    assert client.post(f"/api/campaigns/{c['id']}/session/end", headers=admin).json()["status"] == "ended"
