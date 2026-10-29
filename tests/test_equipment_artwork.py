import asyncio
import io
from datetime import timedelta

import pytest
from PIL import Image

from app.agents.portraits import ImageReply, PortraitError
from app.db.models import Character, Entity, now
from tests.game import party
from tests.test_location_artwork import db


@pytest.fixture
def gear_world(client, admin, tmp_path):
    campaign, (player, other), hero = party(client, admin, players=2, start=False, master={"type": "owner"})
    cid, hid = campaign["id"], hero["id"]
    card = client.get(f"/api/campaigns/{cid}/characters/{hid}", headers=player).json()
    item = card["combat"]["inventory"][0]
    base = f"/api/campaigns/{cid}/characters/{hid}/items"
    url = f"{base}/{item['id']}/artwork"
    output = io.BytesIO()
    Image.new("RGB", (1024, 768), "#887755").save(output, "PNG")

    class Generator:
        model = "comfyui/test"
        timeout_seconds = 600
        calls = 0
        fail = False
        data = output.getvalue()

        async def generate(self, description):
            self.calls += 1
            if self.fail:
                raise PortraitError("unavailable")
            return ImageReply(self.data, "image/png", self.model, cost_known=True)

    class Translator:
        timeout_seconds = 20
        payloads = []

        async def translate(self, session, source, campaign_id=None):
            self.payloads.append(source)
            return {"appearance": "One complete isolated steel sword.", "identity": "", "personality": ""}

    gen, translator = Generator(), Translator()
    client.app.state.equipment_artwork_generator = gen
    client.app.state.equipment_artwork_translator = translator
    client.app.state.equipment_artwork_media_dir = tmp_path
    return cid, hid, player, other, item, base, url, gen, translator


def test_starter_generation_is_read_only_cached_and_has_small_thumbnail(client, admin, gear_world):
    cid, hid, player, other, item, base, url, gen, translator = gear_world
    card_url = f"/api/campaigns/{cid}/characters/{hid}"
    before = client.get(card_url, headers=player).json()
    assert client.get(url, headers=player).json()["status"] == "idle"
    result = client.post(url, headers=player, json={"request_key": "first"})
    assert result.status_code == 200, result.text
    art = result.json()
    assert art["status"] == "ready"
    assert client.get(art["image_url"], headers=player).content == gen.data
    thumb = client.get(art["thumbnail_url"], headers=player)
    assert thumb.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(thumb.content)) as image:
        assert image.size == (256, 192)
    assert len(thumb.content) < len(gen.data)
    assert client.get(art["image_url"]).status_code == 401
    assert client.get(art["image_url"], headers=other).status_code == 403
    assert client.get(art["thumbnail_url"], headers=admin).status_code == 200
    assert client.post(url, headers=player, json={"request_key": "first"}).json() == art
    assert client.post(url, headers=player, json={"request_key": "second"}).json() == art
    assert gen.calls == 1 and len(translator.payloads) == 1
    assert set(translator.payloads[0]) == {"identity", "appearance", "personality"}
    assert client.get(card_url, headers=player).json() == before

    async def read(session):
        hero = await session.get(Character, hid)
        return hero.resources.get("inventory_initialized"), await session.get(Entity, item["id"])

    initialized, row = db(client, read)
    assert not initialized and row is None


def test_identical_instances_share_art_but_different_descriptions_do_not(client, gear_world):
    cid, hid, player, _, item, base, url, gen, _ = gear_world
    first = client.post(url, headers=player, json={"request_key": "first"}).json()

    async def setup(session):
        from app.core.universal.inventory import create_item, ensure_inventory
        from app.rules.universal.items import ItemProfile

        await ensure_inventory(session, cid, hid)
        profile = ItemProfile.model_validate({k: v for k, v in item.items() if k in ItemProfile.model_fields})
        same = await create_item(session, cid, hid, profile, "same")
        different = await create_item(
            session,
            cid,
            hid,
            profile.model_copy(update={"description": "С золотым узором"}),
            "different",
        )
        return same.id, different.id

    same, different = db(client, setup)
    shared = client.post(f"{base}/{same}/artwork", headers=player, json={"request_key": "same"})
    assert shared.status_code == 200 and gen.calls == 1
    assert client.get(shared.json()["image_url"], headers=player).content == gen.data
    # URLs are bound to the authorized item, even when their underlying saved art is shared.
    assert shared.json()["image_url"].split("/")[-1] == first["image_url"].split("/")[-1]
    distinct = client.post(f"{base}/{different}/artwork", headers=player, json={"request_key": "different"})
    assert distinct.status_code == 200 and gen.calls == 2
    assert distinct.json()["image_url"].split("/")[-1] != first["image_url"].split("/")[-1]


def test_private_inventory_hidden_items_and_receipt_binding(client, gear_world):
    cid, hid, player, other, item, base, url, gen, _ = gear_world
    assert client.get(url, headers=other).status_code == 403
    assert client.post(url, headers=other, json={"request_key": "no"}).status_code == 403
    assert client.get(url.replace(item["id"], "unknown"), headers=player).status_code == 404
    first = client.post(url, headers=player, json={"request_key": "first"}).json()
    armor = client.get(f"/api/campaigns/{cid}/characters/{hid}", headers=player).json()["combat"]["inventory"][1]
    reused = client.post(f"{base}/{armor['id']}/artwork", headers=player, json={"request_key": "first"})
    assert reused.status_code == 409
    assert client.post(url, headers=player, json={"request_key": "cached"}).status_code == 200
    reused = client.post(f"{base}/{armor['id']}/artwork", headers=player, json={"request_key": "cached"})
    assert reused.status_code == 409

    async def hide(session):
        from app.core.universal.inventory import ensure_inventory

        await ensure_inventory(session, cid, hid)
        row = await session.get(Entity, item["id"])
        row.state = {**row.state, "hidden": True}

    db(client, hide)
    assert client.get(url, headers=player).status_code == 404
    assert client.get(first["image_url"], headers=player).status_code == 404
    assert gen.calls == 1


def test_failed_attempt_requires_new_key_and_corrupt_image_never_publishes(client, gear_world):
    _, _, player, _, _, _, url, gen, _ = gear_world
    gen.fail = True
    for _ in range(2):
        assert client.post(url, headers=player, json={"request_key": "bad"}).status_code == 409
    assert gen.calls == 1
    gen.fail = False
    gen.data = b"\x89PNG\r\n\x1a\nnot-an-image"
    assert client.post(url, headers=player, json={"request_key": "corrupt"}).status_code == 409
    assert client.get(url, headers=player).json()["image_url"] is None


def test_pending_claim_is_shared_and_expired_work_can_recover(client, gear_world):
    from app.core.equipment_artwork import digest, public_source
    from app.db.models import EquipmentArtwork

    cid, _, player, _, item, _, url, gen, _ = gear_world

    async def claim(session):
        session.add(
            EquipmentArtwork(
                id="ea_pending",
                campaign_id=cid,
                request_key="pending",
                source_digest=digest(public_source(item)),
                status="pending",
                lease_until=now() + timedelta(minutes=10),
            )
        )

    db(client, claim)
    assert client.get(url, headers=player).json()["status"] == "pending"
    assert client.post(url, headers=player, json={"request_key": "another"}).status_code == 409
    assert gen.calls == 0

    async def expire(session):
        (await session.get(EquipmentArtwork, "ea_pending")).lease_until = now() - timedelta(seconds=1)

    db(client, expire)
    assert client.post(url, headers=player, json={"request_key": "new"}).status_code == 200
    assert gen.calls == 1


def test_simultaneous_clicks_share_one_generation(client, gear_world):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    _, _, player, _, _, _, url, gen, _ = gear_world
    entered, release = threading.Event(), threading.Event()

    async def slow(description):
        gen.calls += 1
        entered.set()
        assert await asyncio.to_thread(release.wait, 10)
        return ImageReply(gen.data, "image/png", gen.model, cost_known=True)

    gen.generate = slow
    with ThreadPoolExecutor() as pool:
        first = pool.submit(client.post, url, headers=player, json={"request_key": "first"})
        try:
            assert entered.wait(10)
            other = client.post(url, headers=player, json={"request_key": "second"})
            assert other.status_code == 409 and other.json()["detail"]["code"] == "artwork_pending"
        finally:
            release.set()
        result = first.result(timeout=10)
        assert result.status_code == 200, result.text
    assert gen.calls == 1


def test_description_change_during_generation_never_publishes_old_art(client, gear_world):
    cid, hid, player, _, item, _, url, gen, _ = gear_world

    async def materialize(session):
        from app.core.universal.inventory import ensure_inventory

        await ensure_inventory(session, cid, hid)

    db(client, materialize)
    original = gen.generate

    async def changed(description):
        reply = await original(description)
        async with client.app.state.sessionmaker() as session:
            from app.core.universal.inventory import state_of, store

            row = await session.get(Entity, item["id"])
            state = state_of(row)
            state.profile.description = "Полностью новое описание"
            store(row, state)
            await session.commit()
        return reply

    gen.generate = changed
    assert client.post(url, headers=player, json={"request_key": "old"}).status_code == 409
    assert client.get(url, headers=player).json()["image_url"] is None
    assert not list(client.app.state.equipment_artwork_media_dir.glob("equipment/*"))


def test_equipment_translation_is_accounted_separately(client, gear_world, settings):
    from sqlalchemy import select

    from app.agents.equipment_images import create_equipment_translator
    from app.agents.llm import LLMReply, ScriptedLLM
    from app.db.models import LlmCall

    _, _, player, _, _, _, url, _, _ = gear_world
    llm = ScriptedLLM([LLMReply(text="One complete isolated steel sword.", model="technical/test", cost=0.001)])
    client.app.state.equipment_artwork_translator = create_equipment_translator(llm, settings)
    result = client.post(url, headers=player, json={"request_key": "translated"})
    assert result.status_code == 200, result.text

    async def calls(session):
        return list(await session.scalars(select(LlmCall).where(LlmCall.purpose.like("equipment_%"))))

    rows = db(client, calls)
    assert {r.purpose for r in rows} == {"equipment_illustration", "equipment_artwork_translation"}
    assert all(r.error is None for r in rows)
    assert "object" in llm.requests[0]["messages"][0]["content"]


def test_concurrent_cached_receipts_replay_without_duplicate_images(client, gear_world, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.core import equipment_artwork as service

    _, _, player, _, _, _, url, gen, _ = gear_world
    ready = client.post(url, headers=player, json={"request_key": "created"}).json()
    original_status = service.status
    barrier = threading.Barrier(2)

    async def synchronized(*args, **kwargs):
        result = await original_status(*args, **kwargs)
        await asyncio.to_thread(barrier.wait, 10)
        return result

    monkeypatch.setattr(service, "status", synchronized)
    with ThreadPoolExecutor() as pool:
        requests = [
            pool.submit(client.post, url, headers=player, json={"request_key": "cached-race"}) for _ in range(2)
        ]
        responses = [request.result(timeout=15) for request in requests]
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json() == ready for response in responses)
    assert gen.calls == 1
