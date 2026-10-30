import asyncio
import json

import pytest
from sqlalchemy import select

from app.agents.portraits import ImageReply, PortraitError
from app.core.world import get_scene
from app.db.models import Entity
from tests.test_api import invite, make_campaign, register
from tests.test_hero_portraits import PNG


def db(client, function):
    async def run():
        async with client.app.state.sessionmaker() as session:
            result = await function(session)
            await session.commit()
            return result

    return asyncio.run(run())


@pytest.fixture
def artwork_world(client, root, tmp_path):
    campaign = make_campaign(client, root)
    cid = campaign["id"]

    async def setup(session):
        session.add_all(
            [
                Entity(
                    id="art_room",
                    campaign_id=cid,
                    kind="location",
                    name="Лесная поляна",
                    description="На поляне растут древние дубы.",
                    state={"secret": "SECRET-RUINS"},
                ),
                Entity(
                    id="art_hidden", campaign_id=cid, kind="location", name="SECRET-ROOM", description="SECRET-TREASURE"
                ),
                Entity(
                    id="art_object",
                    campaign_id=cid,
                    kind="object",
                    name="SECRET-TRAP",
                    location_id="art_room",
                    state={"hidden": True},
                ),
            ]
        )
        (await get_scene(session, cid)).location_id = "art_room"

    db(client, setup)

    class Generator:
        model = "comfyui/test"
        timeout_seconds = 600
        calls = 0
        fail = False

        async def generate(self, description):
            self.calls += 1
            if self.fail:
                raise PortraitError("comfyui_unavailable")
            return ImageReply(PNG, "image/png", self.model, cost_known=True)

    class Translator:
        timeout_seconds = 20
        payloads = []

        async def translate(self, session, description, campaign_id=None):
            self.payloads.append(description)
            return {"appearance": "Ancient oak trees in a forest clearing.", "identity": "", "personality": ""}

    generator, translator = Generator(), Translator()
    client.app.state.location_artwork_generator = generator
    client.app.state.location_artwork_translator = translator
    client.app.state.location_artwork_media_dir = tmp_path
    return cid, f"/api/campaigns/{cid}/locations/art_room/artwork", generator, translator


def test_location_image_is_generated_once_cached_and_never_uses_secrets(client, root, artwork_world):
    cid, url, generator, translator = artwork_world
    status = client.get(url, headers=root)
    assert status.status_code == 200 and status.json()["status"] == "idle"
    assert generator.calls == 0
    response = client.post(url, headers=root, json={"request_key": "one"})
    assert response.status_code == 200, response.text
    image = response.json()["image_url"]
    assert response.json()["status"] == "ready" and image
    assert client.get(image, headers=root).content == PNG
    assert client.get(image).status_code == 401
    assert client.post(url, headers=root, json={"request_key": "one"}).json()["image_url"] == image
    assert client.post(url, headers=root, json={"request_key": "two"}).json()["image_url"] == image
    assert client.get(url, headers=root).json()["image_url"] == image
    assert generator.calls == 1 and len(translator.payloads) == 1
    assert "SECRET" not in json.dumps(translator.payloads, ensure_ascii=False)
    assert "древние дубы" in translator.payloads[0]["appearance"]


def test_hidden_foreign_locations_and_players_cannot_start_generation(client, root, admin, artwork_world):
    cid, url, generator, _ = artwork_world
    hidden = url.replace("art_room", "art_hidden")
    assert client.post(hidden, headers=root, json={"request_key": "hidden"}).status_code == 404
    assert client.get(hidden, headers=root).status_code == 404
    assert client.get(url, headers=admin).status_code == 404
    player = register(client, invite(client, root, cid)["token"], "Художник")
    assert client.get(url, headers=player).json()["can_generate"] is False
    assert client.post(url, headers=player, json={"request_key": "player"}).status_code == 403
    assert generator.calls == 0
    image = client.post(url, headers=root, json={"request_key": "owner"}).json()["image_url"]
    assert client.get(image, headers=player).content == PNG
    assert client.get(image, headers=admin).status_code == 404


def test_failed_refresh_keeps_previous_image_and_failed_receipt_is_not_replayed(client, root, artwork_world):
    _, url, generator, _ = artwork_world
    before = client.post(url, headers=root, json={"request_key": "ok"}).json()["image_url"]
    generator.fail = True
    for _ in range(2):
        result = client.post(url, headers=root, json={"request_key": "bad", "regenerate": True})
        assert result.status_code == 409
    assert generator.calls == 2
    assert client.get(url, headers=root).json()["image_url"] == before
    assert client.get(before, headers=root).content == PNG


def test_changed_description_is_marked_stale_and_can_be_explicitly_updated(client, root, artwork_world):
    _, url, generator, _ = artwork_world
    before = client.post(url, headers=root, json={"request_key": "ok"}).json()["image_url"]

    async def change(session):
        (await session.get(Entity, "art_room")).description = "На поляне лежит снег."

    db(client, change)
    assert client.get(url, headers=root).json()["stale"] is True
    assert client.post(url, headers=root, json={"request_key": "reuse"}).json()["image_url"] == before
    after = client.post(url, headers=root, json={"request_key": "refresh", "regenerate": True})
    assert after.status_code == 200 and after.json()["stale"] is False
    assert after.json()["image_url"] != before and generator.calls == 2


def test_pending_claim_prevents_duplicate_work_and_recovers_after_expiry(client, root, artwork_world):
    from datetime import timedelta

    from app.db.models import LocationArtwork, now

    cid, url, generator, _ = artwork_world

    async def pending(session):
        session.add(
            LocationArtwork(
                id="la_pending",
                campaign_id=cid,
                location_id="art_room",
                request_key="pending",
                source_digest="0" * 64,
                status="pending",
                lease_until=now() + timedelta(minutes=12),
            )
        )

    db(client, pending)
    assert client.get(url, headers=root).json()["status"] == "pending"
    assert client.post(url, headers=root, json={"request_key": "duplicate"}).status_code == 409
    assert generator.calls == 0

    async def expire(session):
        row = await session.scalar(select(LocationArtwork).where(LocationArtwork.id == "la_pending"))
        row.lease_until = now() - timedelta(seconds=1)

    db(client, expire)
    response = client.post(url, headers=root, json={"request_key": "new"})
    assert response.status_code == 200 and generator.calls == 1


def test_location_translation_has_environment_prompt_and_separate_accounting(client, root, artwork_world):
    from app.agents.llm import LLMReply, ScriptedLLM
    from app.agents.location_images import create_location_translator
    from app.config import Settings
    from app.db.models import LlmCall

    _, url, _, _ = artwork_world
    llm = ScriptedLLM(
        [
            LLMReply(
                text='{"place": "forest clearing", "landmarks": ["ancient oaks", "mossy stones"], "side": "", "light": "soft morning", "exits": []}',
                tokens_in=50,
                tokens_out=12,
                cost=0.001,
                cost_known=True,
            )
        ]
    )
    client.app.state.location_artwork_translator = create_location_translator(llm, Settings())
    response = client.post(url, headers=root, json={"request_key": "translate"})
    assert response.status_code == 200, response.text
    assert "location" in llm.requests[0]["messages"][0]["content"]
    assert "SECRET" not in json.dumps(llm.requests, ensure_ascii=False)

    async def costs(session):
        return list(await session.scalars(select(LlmCall).where(LlmCall.purpose == "location_artwork_translation")))

    (audit,) = db(client, costs)
    assert audit.cost == 0.001 and audit.cost_known and audit.error is None


def test_landscape_workflow_uses_eye_level_composition_without_character_crop():
    import httpx

    from app.agents.location_images import create_location_generator
    from app.config import Settings

    def respond(request):
        if request.url.path == "/prompt":
            graph = json.loads(request.content)["prompt"]
            assert graph["5"]["inputs"]["width"] == 768 and graph["5"]["inputs"]["height"] == 512
            text = graph["6"]["inputs"]["text"]
            assert "eye-level view" in text and "head and shoulders" not in text
            return httpx.Response(200, json={"prompt_id": "job"})
        if request.url.path == "/history/job":
            return httpx.Response(
                200,
                json={
                    "job": {
                        "status": {"completed": True},
                        "outputs": {"9": {"images": [{"filename": "room.png", "type": "output"}]}},
                    }
                },
            )
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    generator = create_location_generator(Settings())
    generator.transport = httpx.MockTransport(respond)
    reply = asyncio.run(generator.generate({"appearance": "Ancient oak forest"}))
    assert reply.data == PNG


def test_location_prompt_is_composed_from_model_json_with_fixed_weights():
    import pytest

    from app.agents.location_images import compose_location_prompt

    reply = (
        '```json\n{"place": "tavern yard", "landmarks": ["hitching rail (oak)", "rain barrel", "dark horse", "extra"],'
        ' "side": "low fence on the right", "light": "evening", "exits": ["low door"]}\n```'
    )
    assert compose_location_prompt(reply) == (
        "tavern yard, (evening, dim low light:1.3), (hitching rail oak:1.3), (rain barrel:1.2), dark horse, "
        "low fence on the right, low door"
    )
    for bad in ("no json at all", '{"place": "", "landmarks": ["x"]}', '{"place": "yard", "landmarks": []}'):
        with pytest.raises(ValueError):
            compose_location_prompt(bad)


def test_location_artwork_migration_preserves_existing_rooms(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect, text

    from app.db.session import make_engine

    async def run():
        engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
        try:
            async with engine.begin() as connection:

                def migrate(conn):
                    config = Config("alembic.ini")
                    config.attributes["connection"] = conn
                    command.upgrade(config, "universal_0008")
                    conn.execute(
                        text(
                            "INSERT INTO users (id,name,password_hash,platform_role,created_at) "
                            "VALUES ('u1','Owner','hash','player',CURRENT_TIMESTAMP)"
                        )
                    )
                    command.upgrade(config, "head")
                    assert "location_artworks" in inspect(conn).get_table_names()
                    assert conn.execute(text("SELECT name FROM users WHERE id='u1'")).scalar() == "Owner"
                    command.check(config)

                await connection.run_sync(migrate)
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_simultaneous_requests_share_one_generation(client, root, artwork_world):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    _, url, generator, _ = artwork_world
    entered, release = threading.Event(), threading.Event()

    async def slow(description):
        generator.calls += 1
        entered.set()
        assert await asyncio.to_thread(release.wait, 10)
        return ImageReply(PNG, "image/png", generator.model)

    generator.generate = slow
    with ThreadPoolExecutor(1) as pool:
        first = pool.submit(client.post, url, headers=root, json={"request_key": "first"})
        try:
            assert entered.wait(10)
            second = client.post(url, headers=root, json={"request_key": "second"})
            assert second.status_code == 409 and generator.calls == 1
        finally:
            release.set()
        assert first.result().status_code == 200


def test_description_changed_during_generation_does_not_publish_wrong_image(client, root, artwork_world):
    _, url, generator, _ = artwork_world
    before = client.post(url, headers=root, json={"request_key": "before"}).json()["image_url"]

    async def changed(description):
        async with client.app.state.sessionmaker() as session:
            (await session.get(Entity, "art_room")).description = "Теперь здесь заснеженная поляна."
            await session.commit()
        return ImageReply(PNG, "image/png", generator.model)

    generator.generate = changed
    response = client.post(url, headers=root, json={"request_key": "changed", "regenerate": True})
    assert response.status_code == 409
    assert client.get(url, headers=root).json()["image_url"] == before


def test_location_translation_purpose_fits_database_column():
    from app.agents.llm import ScriptedLLM
    from app.agents.location_images import create_location_translator
    from app.config import Settings
    from app.db.models import LlmCall

    translator = create_location_translator(ScriptedLLM([]), Settings())
    assert len(translator.purpose) <= LlmCall.__table__.c.purpose.type.length
