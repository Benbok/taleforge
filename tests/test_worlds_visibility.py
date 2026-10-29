import pytest

from tests.game import import_base
from tests.test_author_secret_access import publish
from tests.test_universal_studio import BASE

CATALOG = "/api/adventures/catalog"


@pytest.fixture
def world(client, root, admin, settings):
    import_base(settings)
    version_id = publish(client, root)
    project = client.get(BASE, headers=root).json()[0]
    return dict(version=version_id, project=project["id"])


def listed(client, headers):
    return [e["version_id"] for e in client.get(CATALOG, headers=headers).json()]


def launch(client, headers, version_id, key="k"):
    return client.post(f"/api/adventures/{version_id}/games", headers=headers, json={"request_key": key})


def test_unlisting_hides_the_world_from_the_catalog_and_from_foreign_launch(client, root, admin, world):
    assert world["version"] in listed(client, admin)
    r = client.put(f"{BASE}/{world['project']}/catalog", headers=root, json={"listed": False})
    assert r.status_code == 200 and r.json()["listed"] is False
    assert world["version"] not in listed(client, admin)
    assert launch(client, admin, world["version"]).status_code == 404  # no way around the catalog
    assert launch(client, root, world["version"]).status_code == 201  # the author keeps their own world
    assert client.get(BASE, headers=root).json()[0]["listed"] is False


def test_relisting_brings_the_world_back_and_running_games_are_untouched(client, root, admin, world):
    game = launch(client, admin, world["version"], key="before").json()["campaign_id"]
    client.put(f"{BASE}/{world['project']}/catalog", headers=root, json={"listed": False})
    assert client.get(f"/api/campaigns/{game}", headers=admin).status_code == 200  # a running game stays
    client.put(f"{BASE}/{world['project']}/catalog", headers=root, json={"listed": True})
    assert world["version"] in listed(client, admin)
    assert launch(client, admin, world["version"], key="after").status_code == 201


def test_archiving_removes_the_project_from_the_list_and_the_catalog(client, root, admin, world):
    game = launch(client, admin, world["version"]).json()["campaign_id"]
    assert client.post(f"{BASE}/{world['project']}/archive", headers=root).status_code == 204
    assert client.get(BASE, headers=root).json() == []
    assert world["version"] not in listed(client, admin)
    assert launch(client, admin, world["version"], key="new").status_code == 404
    assert client.get(f"{BASE}/{world['project']}", headers=root).status_code == 404
    assert client.get(f"/api/campaigns/{game}", headers=admin).status_code == 200  # games already started go on


def test_only_the_author_changes_visibility(client, root, admin, world):
    assert client.put(f"{BASE}/{world['project']}/catalog", headers=admin, json={"listed": False}).status_code == 404
    assert client.post(f"{BASE}/{world['project']}/archive", headers=admin).status_code == 404
    assert world["version"] in listed(client, admin)
