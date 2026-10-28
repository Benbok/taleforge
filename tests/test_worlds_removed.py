def test_builtin_world_api_is_gone(client):
    assert client.get("/api/worlds").status_code == 404
    assert client.get("/api/worlds/echo-leviathans").status_code == 404


def test_pack_admin_api_is_gone(client, admin):
    assert client.get("/api/packs", headers=admin).status_code == 404
    assert client.post("/api/admin/packs", content=b"x", headers=admin).status_code in (404, 405)
