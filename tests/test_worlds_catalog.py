import asyncio

from app.db.models import AdventureVersion
from tests.test_author_secret_access import make_player, publish
from tests.test_universal_studio import BASE, create

KEYS = {"version_id", "project_id", "title", "author_name", "version", "public_summary", "published_at"}


def catalog(client, headers):
    return client.get("/api/adventures/catalog", headers=headers)


def second_version(client, version_id):
    """A later published version of the same project."""

    async def go():
        async with client.app.state.sessionmaker() as session:
            first = await session.get(AdventureVersion, version_id)
            session.add(
                AdventureVersion(
                    project_id=first.project_id,
                    version=first.version + 1,
                    source_revision=first.source_revision,
                    source_digest=first.source_digest,
                    publish_request_key="again",
                    publish_input_digest=first.publish_input_digest,
                    public_summary=first.public_summary,
                    bundle=first.bundle,
                    validation_report=first.validation_report,
                )
            )
            await session.commit()

    asyncio.run(go())


def test_catalog_lists_latest_version_of_every_author(client, root, admin):
    first = publish(client, root)
    second_version(client, first)
    other = client.post(BASE, headers=admin, json={"title": "Другой мир", "studio": create_fields(client, root)})
    assert other.status_code == 201, other.text
    rows = catalog(client, admin).json()
    assert len(rows) == 1 and rows[0]["version"] == 2
    assert rows[0]["author_name"] == "root"


def create_fields(client, root):
    from tests.test_universal_studio import FIELDS

    return FIELDS


def test_catalog_excludes_unpublished_projects(client, root):
    create(client, root)
    assert catalog(client, root).json() == []


def test_catalog_has_only_public_keys(client, root):
    publish(client, root)
    rows = catalog(client, root).json()
    assert rows and set(rows[0]) == KEYS
    assert "SECRET-PLOT" not in catalog(client, root).text


def test_catalog_requires_login(client):
    assert catalog(client, {}).status_code == 401


def test_catalog_visible_to_a_player(client, root):
    publish(client, root)
    player = make_player(client, root)
    assert catalog(client, player).status_code == 200 and len(catalog(client, player).json()) == 1
