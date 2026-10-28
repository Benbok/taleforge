def test_builtin_world_api_is_gone(client):
    assert client.get("/api/worlds").status_code == 404
    assert client.get("/api/worlds/echo-leviathans").status_code == 404
