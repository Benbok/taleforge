# ruff: noqa: F811 -- pytest fixture re-export
import pytest

from tests.test_api import make_campaign
from tests.test_equipment_artwork import gear_world  # noqa: F401
from tests.universal_helpers import create_hero


def test_library_equipment_generates_without_campaign_and_is_private(client, root, gear_world):
    _, _, _, other, _, _, _, gen, _ = gear_world
    hid = create_hero(client, root)
    base = f"/api/me/characters/{hid}"
    before = client.get(base, headers=root).json()
    url = base + "/equipment/weapon/artwork"
    assert client.get(url, headers=root).json()["status"] == "idle"
    result = client.post(url, headers=root, json={"request_key": "library"})
    assert result.status_code == 200, result.text
    art = result.json()
    assert client.get(art["thumbnail_url"], headers=root).status_code == 200
    assert client.get(art["image_url"], headers=root).content == gen.data
    assert client.get(url, headers=other).status_code == 404
    assert client.get(art["image_url"], headers=other).status_code == 404
    assert client.get(base, headers=root).json() == before
    assert client.post(url, headers=root, json={"request_key": "library"}).json() == art
    assert gen.calls == 1
    assert client.get(base + "/equipment/unknown/artwork", headers=root).status_code == 404


def test_library_and_campaign_copy_share_images_in_both_directions(client, root, gear_world):
    _, _, _, _, _, _, _, gen, _ = gear_world
    hid = create_hero(client, root)
    cid = make_campaign(client, root, owner_plays=True)["id"]
    copied = client.post(f"/api/campaigns/{cid}/characters/from-library/{hid}", headers=root)
    assert copied.status_code == 201, copied.text
    hero_id = copied.json()["id"]
    base = f"/api/campaigns/{cid}/characters/{hero_id}"
    inventory = client.get(base, headers=root).json()["combat"]["inventory"]
    weapon = next(item for item in inventory if item["kind"] == "weapon")
    armor = next(item for item in inventory if item["kind"] == "armor")
    game_weapon = f"{base}/items/{weapon['id']}/artwork"
    library_weapon = f"/api/me/characters/{hid}/equipment/weapon/artwork"
    assert client.post(game_weapon, headers=root, json={"request_key": "game"}).status_code == 200
    shared = client.get(library_weapon, headers=root)
    assert shared.status_code == 200 and shared.json()["status"] == "ready", shared.text
    assert client.get(shared.json()["image_url"], headers=root).content == gen.data
    saved_library_image = shared.json()["image_url"]
    # The reverse path: create the armor in the library, then view it in the campaign inventory.
    library_armor = f"/api/me/characters/{hid}/equipment/armor/artwork"
    result = client.post(library_armor, headers=root, json={"request_key": "armor"})
    assert result.status_code == 200, result.text
    game_armor = f"{base}/items/{armor['id']}/artwork"
    shared = client.get(game_armor, headers=root).json()
    assert shared["status"] == "ready"
    assert client.get(shared["image_url"], headers=root).status_code == 200
    assert client.post(game_armor, headers=root, json={"request_key": "cached"}).status_code == 200
    assert gen.calls == 2
    deleted = client.delete(f"/api/campaigns/{cid}", headers=root)
    assert deleted.status_code in (200, 204), deleted.text
    assert client.get(saved_library_image, headers=root).content == gen.data


def test_library_and_linked_game_share_a_pending_generation(client, root, gear_world):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.agents.portraits import ImageReply

    _, _, _, _, _, _, _, gen, _ = gear_world
    hid = create_hero(client, root)
    cid = make_campaign(client, root, owner_plays=True)["id"]
    hero = client.post(f"/api/campaigns/{cid}/characters/from-library/{hid}", headers=root).json()
    base = f"/api/campaigns/{cid}/characters/{hero['id']}"
    item = client.get(base, headers=root).json()["combat"]["inventory"][0]
    game_url = f"{base}/items/{item['id']}/artwork"
    library_url = f"/api/me/characters/{hid}/equipment/{item['kind']}/artwork"
    entered, release = threading.Event(), threading.Event()

    async def slow(description):
        gen.calls += 1
        entered.set()
        assert await asyncio.to_thread(release.wait, 10)
        return ImageReply(gen.data, "image/png", gen.model)

    gen.generate = slow
    with ThreadPoolExecutor() as pool:
        first = pool.submit(client.post, game_url, headers=root, json={"request_key": "game"})
        try:
            assert entered.wait(10)
            second = client.post(library_url, headers=root, json={"request_key": "library"})
            assert second.status_code == 409, second.text
        finally:
            release.set()
        assert first.result(timeout=10).status_code == 200
    assert gen.calls == 1


def test_library_migration_preserves_populated_cache_with_foreign_keys(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from app.db.models import Campaign, User

    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        config = Config("alembic.ini")
        config.attributes["connection"] = conn
        command.upgrade(config, "universal_0011")
        with Session(conn) as session:
            session.add(User(id="u1", name="Owner", password_hash="hash"))
            session.flush()
            session.add(Campaign(id="c1", owner_id="u1", name="Preserved", ruleset_version="universal.v1"))
            session.flush()
            session.commit()
        conn.execute(
            text(
                "INSERT INTO equipment_artworks"
                "(id,campaign_id,request_key,source_digest,status,lease_until,created_at) "
                "VALUES ('original','c1','one','digest','ready',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO equipment_artworks"
                "(id,campaign_id,request_key,source_digest,status,reused_from,lease_until,created_at) "
                "VALUES ('receipt','c1','two','digest','ready','original',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        conn.commit()
        command.upgrade(config, "head")
        assert set(conn.execute(text("SELECT id FROM equipment_artworks")).scalars()) == {"original", "receipt"}
        assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    engine.dispose()


@pytest.mark.parametrize("old_scope", ["campaign", "another-owner"])
def test_linked_hero_recovers_expired_campaign_claim_from_another_scope(client, root, gear_world, old_scope):
    from datetime import timedelta

    from app.core.equipment_artwork import digest, public_source
    from app.db.models import EquipmentArtwork, now
    from tests.test_location_artwork import db

    hid = create_hero(client, root)
    cid = make_campaign(client, root, owner_plays=True)["id"]
    hero = client.post(f"/api/campaigns/{cid}/characters/from-library/{hid}", headers=root).json()
    base = f"/api/campaigns/{cid}/characters/{hero['id']}"
    item = client.get(base, headers=root).json()["combat"]["inventory"][0]

    async def seed(session):
        session.add(
            EquipmentArtwork(
                id="old_claim",
                campaign_id=cid,
                request_key="old",
                source_digest=digest(public_source(item)),
                pending_scope="campaign:" + cid if old_scope == "campaign" else "owner:another",
                status="pending",
                lease_until=now() - timedelta(seconds=1),
            )
        )

    db(client, seed)
    result = client.post(f"{base}/items/{item['id']}/artwork", headers=root, json={"request_key": "recover"})
    assert result.status_code == 200, result.text
