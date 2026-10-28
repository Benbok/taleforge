import asyncio

import pytest
from sqlalchemy import select

from app.agents.llm import ScriptedLLM
from app.core.authoring.contracts import InstanceOptions
from app.core.authoring.instances import instantiate_adventure
from app.db.models import AdventureVersion, User
from tests.game import import_base
from tests.test_universal_studio import BASE, create, review_reply


def publish(client, root):
    project = create(client, root)
    client.app.state.studio_llm = ScriptedLLM([review_reply()])
    url = f"{BASE}/{project['id']}/studio"
    client.post(url + "/review", headers=root, json={"expected_revision": project["draft_revision"]})
    accepted = client.post(
        url + "/accept", headers=root, json={"expected_revision": project["draft_revision"], "request_key": "accept"}
    )
    assert accepted.status_code == 201, accepted.text
    return accepted.json()["id"]


def launch_as(client, version_id, user_name):
    """The launching administrator owns the new game and holds the master seat."""

    async def go():
        async with client.app.state.sessionmaker() as session:
            user = await session.scalar(select(User).where(User.name == user_name))
            version = await session.get(AdventureVersion, version_id)
            options = InstanceOptions(name="Game", master={"type": "owner"})
            receipt = await instantiate_adventure(session, user, version, options, f"key-{user_name}")
            await session.commit()
            return receipt.campaign_id

    return asyncio.run(go())


@pytest.fixture
def world(client, root, admin, settings):
    import_base(settings)
    version_id = publish(client, root)
    return dict(
        mine=launch_as(client, version_id, "root"),
        theirs=launch_as(client, version_id, "Arty"),
    )


def plot_of(body):
    return (body or {}).get("plot") or {}


def test_author_reads_own_launch_secrets(client, root, world):
    r = client.get(f"/api/campaigns/{world['mine']}/secrets", headers=root)
    assert r.status_code == 200, r.text
    assert "SECRET-PLOT" in r.text or plot_of(r.json()) or r.json()["setting"]


def test_other_admin_cannot_read_or_write_author_secrets(client, admin, world):
    cid = world["theirs"]
    assert client.get(f"/api/campaigns/{cid}/secrets", headers=admin).status_code == 404
    assert client.put(f"/api/campaigns/{cid}/secrets", headers=admin, json={"plot": {}}).status_code == 404


def test_other_admin_plan_has_no_plot(client, admin, world):
    r = client.get(f"/api/campaigns/{world['theirs']}/plan", headers=admin)
    assert r.status_code == 200, r.text
    assert "plan" not in r.json()


def test_other_admin_master_panel_has_no_plot(client, admin, world):
    theirs = client.get(f"/api/campaigns/{world['theirs']}/master-panel", headers=admin)
    assert theirs.status_code == 200, theirs.text
    assert theirs.json()["has_plot"] is False
    assert "plot" not in theirs.json()["tools"]
