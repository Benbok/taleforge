# ruff: noqa: F811 -- pytest fixture re-export
import io

import pytest
from PIL import Image

from tests.test_api import make_campaign
from tests.test_equipment_artwork import gear_world  # noqa: F401
from tests.test_location_artwork import db
from tests.universal_helpers import create_hero


def new_image(gen):
    output = io.BytesIO()
    Image.new("RGB", (768, 768), "#225577").save(output, "PNG")
    gen.data = output.getvalue()


def test_only_platform_admin_can_replace_and_failure_keeps_previous_image(client, admin, gear_world):
    _, _, player, _, _, _, url, gen, _ = gear_world
    original = client.post(url, headers=player, json={"request_key": "first"}).json()
    old_bytes = client.get(original["image_url"], headers=player).content
    assert client.get(url, headers=player).json()["can_regenerate"] is False
    assert client.get(url, headers=admin).json()["can_regenerate"] is True
    body = {"request_key": "replace", "regenerate": True}
    assert client.post(url, headers=player, json=body).status_code == 403
    assert gen.calls == 1
    new_image(gen)
    replacement = client.post(url, headers=admin, json=body)
    assert replacement.status_code == 200, replacement.text
    current = replacement.json()
    assert current["image_url"] != original["image_url"]
    assert client.get(current["image_url"], headers=player).content == gen.data
    assert client.get(original["image_url"], headers=player).content == old_bytes
    assert client.get(url, headers=player).json()["image_url"] == current["image_url"]
    assert client.post(url, headers=admin, json=body).json() == current
    assert gen.calls == 2
    # A request receipt binds the operation as well as the item.
    changed = client.post(url, headers=admin, json={**body, "regenerate": False})
    assert changed.status_code == 409
    gen.fail = True
    failed = {"request_key": "failed-replace", "regenerate": True}
    assert client.post(url, headers=admin, json=failed).status_code == 409
    assert client.post(url, headers=admin, json=failed).status_code == 409
    state = client.get(url, headers=player).json()
    assert state["status"] == "failed" and state["image_url"] == current["image_url"]
    assert gen.calls == 3


def test_replacement_reaches_library_and_game_and_late_old_receipt_cannot_revert_it(client, root, gear_world):
    _, _, _, _, _, _, _, gen, _ = gear_world
    hid = create_hero(client, root)
    url = f"/api/me/characters/{hid}/equipment/weapon/artwork"
    original = client.post(url, headers=root, json={"request_key": "first"}).json()
    cid = make_campaign(client, root, owner_plays=True)["id"]
    hero = client.post(f"/api/campaigns/{cid}/characters/from-library/{hid}", headers=root).json()
    base = f"/api/campaigns/{cid}/characters/{hero['id']}"
    item = client.get(base, headers=root).json()["combat"]["inventory"][0]
    game_url = f"{base}/items/{item['id']}/artwork"
    assert client.post(game_url, headers=root, json={"request_key": "copy"}).status_code == 200
    new_image(gen)
    replacement = client.post(url, headers=root, json={"request_key": "replace", "regenerate": True})
    assert replacement.status_code == 200, replacement.text
    current = replacement.json()
    assert current["image_url"] != original["image_url"]
    assert client.get(game_url, headers=root).json()["image_url"].split("/")[-1] == current["image_url"].split("/")[-1]

    async def late_receipt(session):
        from app.core.equipment_artwork import public_source, save_cached
        from app.core.equipment_artwork_scope import library_item, library_scope
        from app.db.models import LibraryCharacter

        hero = await session.get(LibraryCharacter, hid)
        scope = await library_scope(session, hero.owner_user_id, hid)
        source = public_source(await library_item(session, hero.owner_user_id, hid, "weapon"))
        await save_cached(
            session, scope, source, url, "late-old-cache", original, client.app.state.equipment_artwork_media_dir
        )

    db(client, late_receipt)
    assert client.get(url, headers=root).json()["image_url"] == current["image_url"]
    assert client.get(game_url, headers=root).json()["image_url"].split("/")[-1] == current["image_url"].split("/")[-1]
    assert gen.calls == 2


def test_cache_race_cannot_acknowledge_a_key_already_used_for_regeneration(client, admin, gear_world):
    from app.core.campaigns import Conflict
    from app.core.equipment_artwork import public_source, save_cached
    from app.core.equipment_artwork_scope import ArtworkScope

    cid, _, player, _, item, _, url, _, _ = gear_world
    original = client.post(url, headers=player, json={"request_key": "first"}).json()
    assert client.post(url, headers=admin, json={"request_key": "race", "regenerate": True}).status_code == 200

    async def late_cache_hit(session):
        # The non-regenerate request read its empty receipt before the other request committed.
        await save_cached(
            session,
            ArtworkScope(cid),
            public_source(item),
            url,
            "race",
            original,
            client.app.state.equipment_artwork_media_dir,
        )

    with pytest.raises(Conflict):
        db(client, late_cache_hit)
