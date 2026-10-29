import io

import pytest
from PIL import Image

from app.agents.portraits import ImageReply, PortraitError
from app.db.models import Entity
from tests.game import party
from tests.test_location_artwork import db


@pytest.fixture
def npc_world(client, admin, tmp_path):
    campaign, (player, other), hero = party(client, admin, players=2, start=False, master={"type": "owner"})
    cid = campaign["id"]

    async def setup(session):
        from app.core.world import get_scene
        from app.db.models import Character

        (await get_scene(session, cid)).location_id = "npc_room"
        (await session.get(Character, hero["id"])).location_id = "npc_room"
        (await session.get(Character, hero["id"])).status = "approved"
        session.add_all(
            [
                Entity(id="npc_room", campaign_id=cid, kind="location", name="Площадь"),
                Entity(
                    id="npc_known",
                    campaign_id=cid,
                    kind="creature",
                    name="Лесничий",
                    description="Пожилой эльф в зелёном плаще, серебряные волосы.",
                    location_id="npc_room",
                    state={"attitude": "friendly", "secret_notes": "SECRET-TRAITOR", "motivation": "SECRET-REVENGE"},
                ),
                Entity(
                    id="npc_hidden",
                    campaign_id=cid,
                    kind="creature",
                    name="SECRET-NPC",
                    description="SECRET-LOOK",
                    location_id="npc_room",
                    state={"hidden": True},
                ),
                Entity(
                    id="npc_unknown",
                    campaign_id=cid,
                    kind="creature",
                    name="SECRET-OTHER",
                    description="SECRET-DESCRIPTION",
                    location_id="elsewhere",
                ),
            ]
        )

    db(client, setup)
    buffer = io.BytesIO()
    Image.new("RGB", (768, 768), "#448866").save(buffer, "PNG")

    class Generator:
        model = "comfyui/test"
        timeout_seconds = 600
        calls = 0
        fail = False

        async def generate(self, source):
            self.calls += 1
            if self.fail:
                raise PortraitError("unavailable")
            return ImageReply(buffer.getvalue(), "image/png", self.model, cost_known=True)

    class Translator:
        timeout_seconds = 20
        payloads = []

        async def translate(self, session, source, campaign_id=None):
            self.payloads.append(source)
            return {
                "appearance": "An elderly elf wearing a green cloak, silver hair.",
                "identity": "",
                "personality": "",
            }

    generator, translator = Generator(), Translator()
    client.app.state.npc_portrait_generator = generator
    client.app.state.npc_portrait_translator = translator
    client.app.state.npc_portrait_media_dir = tmp_path
    return cid, hero, player, other, f"/api/campaigns/{cid}/npcs/npc_known/portraits", generator, translator


def test_variants_require_explicit_selection_and_preserve_previous_portrait(client, admin, npc_world):
    _, _, player, _, url, gen, translator = npc_world
    assert client.get(url, headers=admin).json()["variants"] == []
    first = client.post(url, headers=admin, json={"request_key": "first"})
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["selected_id"] is None and len(data["variants"]) == 1
    first_id = data["variants"][0]["id"]
    selected = client.put(url + "/selection", headers=admin, json={"image_id": first_id})
    assert selected.status_code == 200 and selected.json()["selected_id"] == first_id
    second = client.post(url, headers=admin, json={"request_key": "second"}).json()
    assert second["selected_id"] == first_id and len(second["variants"]) == 2
    assert client.post(url, headers=admin, json={"request_key": "second"}).json() == second
    second_id = next(v["id"] for v in second["variants"] if v["id"] != first_id)
    assert (
        client.put(url + "/selection", headers=admin, json={"image_id": second_id}).json()["selected_id"] == second_id
    )
    assert client.put(url + "/selection", headers=admin, json={"image_id": first_id}).json()["selected_id"] == first_id
    visible = client.get(url, headers=player)
    assert visible.status_code == 200, visible.text
    assert visible.json()["selected_id"] == first_id
    gen.fail = True
    assert client.post(url, headers=admin, json={"request_key": "bad"}).status_code == 409
    state = client.get(url, headers=admin).json()
    assert state["selected_id"] == first_id and len(state["variants"]) == 1
    assert gen.calls == 3
    assert "SECRET" not in str(translator.payloads)


def test_selection_hides_older_variants_on_reload_but_new_candidates_can_be_compared(client, admin, npc_world):
    _, _, _, _, url, _, _ = npc_world
    first = client.post(url, headers=admin, json={"request_key": "first"}).json()["variants"][0]["id"]
    second = client.post(url, headers=admin, json={"request_key": "second"}).json()["variants"][0]["id"]
    selected = client.put(url + "/selection", headers=admin, json={"image_id": first}).json()
    assert [v["id"] for v in selected["variants"]] == [first]
    assert [v["id"] for v in client.get(url, headers=admin).json()["variants"]] == [first]
    newer = client.post(url, headers=admin, json={"request_key": "third"}).json()
    assert newer["selected_id"] == first and len(newer["variants"]) == 2
    assert second not in {v["id"] for v in newer["variants"]}


def test_hidden_unknown_npcs_and_other_players_cannot_generate_or_choose(client, admin, root, npc_world):
    _, _, player, _, url, gen, _ = npc_world
    assert client.get(url, headers=player).status_code == 200
    assert client.get(url.replace("npc_known", "npc_hidden"), headers=player).status_code == 404
    assert client.get(url.replace("npc_known", "npc_unknown"), headers=player).status_code == 404
    assert client.get(url, headers=root).status_code == 404
    assert client.post(url, headers=player, json={"request_key": "denied"}).status_code == 403
    data = client.post(url, headers=admin, json={"request_key": "allowed"}).json()
    variant = data["variants"][0]
    assert client.put(url + "/selection", headers=player, json={"image_id": variant["id"]}).status_code == 403
    assert client.get(variant["image_url"], headers=player).status_code == 200
    assert client.get(variant["thumbnail_url"], headers=player).headers["content-type"] == "image/webp"
    assert client.get(variant["image_url"]).status_code == 401
    assert client.get(variant["image_url"], headers=root).status_code == 404
    assert gen.calls == 1


def test_unplaced_npc_generation_never_grants_an_encounter_to_unplaced_heroes(client, admin, npc_world):
    from app.core.world import get_scene
    from app.db.models import Character

    cid, hero, player, _, url, _, _ = npc_world

    async def unplace(session):
        (await session.get(Entity, "npc_known")).location_id = None
        (await session.get(Character, hero["id"])).location_id = None
        (await get_scene(session, cid)).location_id = None

    db(client, unplace)
    assert client.get(url, headers=player).status_code == 404
    result = client.post(url, headers=admin, json={"request_key": "unplaced"})
    assert result.status_code == 200, result.text
    assert client.get(url, headers=player).status_code == 404


def test_changed_public_appearance_cannot_reuse_or_select_old_projection(client, admin, npc_world):
    _, _, _, _, url, _, _ = npc_world
    variant = client.post(url, headers=admin, json={"request_key": "one"}).json()["variants"][0]

    async def change(session):
        (await session.get(Entity, "npc_known")).description = "Эльф в белом плаще, чёрные волосы."

    db(client, change)
    assert client.get(url, headers=admin).json()["variants"] == []
    assert client.get(variant["image_url"], headers=admin).status_code == 404
    assert client.put(url + "/selection", headers=admin, json={"image_id": variant["id"]}).status_code == 404


def test_real_encounter_observation_keeps_npc_portrait_after_leaving_without_new_appearance(client, admin, npc_world):
    from types import SimpleNamespace

    from app.core.object_policy import observe
    from app.db.models import Character, Knowledge

    _, hero, player, _, url, _, _ = npc_world

    async def encounter(session):
        actor = await session.get(Character, hero["id"])
        npc = await session.get(Entity, "npc_known")
        world = SimpleNamespace(entities={npc.id: npc}, characters={actor.id: actor}, place_of=lambda h: h.location_id)
        await observe(SimpleNamespace(session=session, world=world), "npc_room", [])
        knowledge = await session.get(Knowledge, (actor.id, npc.id))
        assert knowledge and knowledge.observed_snapshot["description"] == npc.description

    db(client, encounter)
    data = client.post(url, headers=admin, json={"request_key": "seen"}).json()
    variant = data["variants"][0]
    client.put(url + "/selection", headers=admin, json={"image_id": variant["id"]})

    async def leave(session):
        (await session.get(Character, hero["id"])).location_id = "elsewhere"
        (await session.get(Entity, "npc_known")).description = "SECRET-NEW-APPEARANCE"

    db(client, leave)
    memory = client.get(url, headers=player)
    assert memory.status_code == 200, memory.text
    assert memory.json()["selected_id"] == variant["id"]
    assert client.get(memory.json()["variants"][0]["image_url"], headers=player).status_code == 200


def test_expired_claim_recovers_and_simultaneous_requests_generate_once(client, admin, npc_world):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta

    from app.core.npc_portraits import digest
    from app.db.models import NpcPortrait, now

    cid, _, _, _, url, gen, _ = npc_world

    async def expired(session):
        npc = await session.get(Entity, "npc_known")
        session.add(
            NpcPortrait(
                id="np_expired",
                campaign_id=cid,
                npc_id=npc.id,
                request_key="expired",
                source_digest=digest({"identity": npc.name, "appearance": npc.description, "personality": ""}),
                status="pending",
                lease_until=now() - timedelta(seconds=1),
            )
        )

    db(client, expired)
    original = gen.generate
    entered, release = threading.Event(), threading.Event()

    async def slow(source):
        entered.set()
        assert await asyncio.to_thread(release.wait, 10)
        return await original(source)

    gen.generate = slow
    with ThreadPoolExecutor() as pool:
        first = pool.submit(client.post, url, headers=admin, json={"request_key": "first"})
        try:
            assert entered.wait(10)
            assert client.get(url, headers=admin).json()["status"] == "pending"
            assert client.post(url, headers=admin, json={"request_key": "second"}).status_code == 409
        finally:
            release.set()
        response = first.result(timeout=10)
        assert response.status_code == 200, response.text
    assert gen.calls == 1
