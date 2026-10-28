import pytest

from app.db.models import Campaign
from tests.game import import_base
from tests.test_author_secret_access import make_player, publish


@pytest.fixture
def published(client, root, admin, settings):
    import_base(settings)
    return publish(client, root)


def launch(client, headers, version_id, key="k1", **body):
    return client.post(f"/api/adventures/{version_id}/games", headers=headers, json={"request_key": key, **body})


def campaign_row(client, cid):
    import asyncio

    async def go():
        async with client.app.state.sessionmaker() as session:
            return await session.get(Campaign, cid)

    return asyncio.run(go())


def test_other_admin_launches_published_world_with_defaults(client, admin, published):
    r = launch(client, admin, published)
    assert r.status_code == 201, r.text
    row = campaign_row(client, r.json()["campaign_id"])
    assert row.name == "Glass islands"  # named after the project
    assert row.status != "active"
    assert client.get(f"/api/campaigns/{row.id}", headers=admin).status_code == 200


def test_launch_is_idempotent_per_request_key(client, admin, published):
    a = launch(client, admin, published, key="same").json()["campaign_id"]
    b = launch(client, admin, published, key="same").json()["campaign_id"]
    c = launch(client, admin, published, key="other").json()["campaign_id"]
    assert a == b and a != c


def test_player_cannot_launch(client, root, published):
    player = make_player(client, root)
    assert launch(client, player, published).status_code == 404


def test_unknown_version_is_404(client, admin):
    assert launch(client, admin, "av_missing").status_code == 404


def test_non_author_cannot_take_the_human_master_seat(client, admin, published):
    options = dict(name="Mine", master={"type": "owner"})
    assert launch(client, admin, published, key="own", options=options).status_code == 409


def test_cabinet_edits_what_launch_no_longer_asks(client, admin, published):
    cid = launch(client, admin, published).json()["campaign_id"]
    changed = dict(name="Our table", leveling="milestone", excluded_themes=["cruelty"], tts_enabled=False)
    r = client.patch(f"/api/campaigns/{cid}", headers=admin, json=changed)
    assert r.status_code == 200, r.text
    row = campaign_row(client, cid)
    assert row.name == "Our table"
    assert row.settings["leveling"] == "milestone"
    assert row.settings["excluded_themes"] == ["cruelty"]
    assert row.settings["tts_enabled"] is False


def _db(client, fn):
    import asyncio

    async def go():
        async with client.app.state.sessionmaker() as session:
            out = await fn(session)
            await session.commit()
            return out

    return asyncio.run(go())


def test_other_admin_cannot_launch_a_superseded_version(client, admin, published):
    from app.db.models import AdventureVersion, new_id

    async def add_newer(session):
        old = await session.get(AdventureVersion, published)
        cols = {c.name: getattr(old, c.name) for c in AdventureVersion.__table__.columns}
        cols.update(id=new_id("av"), version=old.version + 1, publish_request_key="accept2")
        session.add(AdventureVersion(**cols))

    _db(client, add_newer)
    assert launch(client, admin, published).status_code == 404


def test_retry_after_the_author_renames_the_world_returns_the_same_game(client, admin, published):
    from app.db.models import AdventureVersion, AuthorProject

    first = launch(client, admin, published, key="retry").json()["campaign_id"]

    async def rename(session):
        v = await session.get(AdventureVersion, published)
        (await session.get(AuthorProject, v.project_id)).title = "Renamed world"

    _db(client, rename)
    again = launch(client, admin, published, key="retry")
    assert again.status_code == 201, again.text
    assert again.json()["campaign_id"] == first
