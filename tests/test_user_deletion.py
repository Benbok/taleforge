"""Удаление учётных записей Super Admin'ом."""

from tests.game import ok


def test_superadmin_deletes_user(client, root, admin):
    created = ok(client.post("/api/auth/signup", json={"name": "Гимли", "password": "pass123"}))
    player = {"Authorization": f"Bearer {created['token']}"}
    users = {u["name"]: u for u in ok(client.get("/api/admin/users", headers=root))}
    gimli = users["Гимли"]["id"]
    root_id = users["root"]["id"]

    assert client.delete(f"/api/admin/users/{gimli}", headers=admin).status_code == 403
    assert client.delete(f"/api/admin/users/{root_id}", headers=root).status_code == 409
    assert client.delete(f"/api/admin/users/{gimli}", headers=root).status_code == 204
    assert "Гимли" not in {u["name"] for u in ok(client.get("/api/admin/users", headers=root))}
    assert client.get("/api/auth/me", headers=player).status_code == 401
    assert client.post("/api/auth/login", json={"name": "Гимли", "password": "pass123"}).status_code == 401
