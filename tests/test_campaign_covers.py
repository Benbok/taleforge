import io

import pytest
from PIL import Image

from app.agents.portraits import ImageReply, PortraitError
from app.db.models import Campaign
from tests.test_api import invite, make_campaign, register
from tests.test_location_artwork import db


def png():
    output = io.BytesIO()
    Image.new("RGB", (1024, 576), "#446688").save(output, "PNG")
    return output.getvalue()


@pytest.fixture
def cover_world(client, root, tmp_path):
    campaign = make_campaign(client, root, public_intro="Туманные горы над долиной.")
    cid = campaign["id"]
    data = png()

    class Generator:
        model = "comfyui/test"
        timeout_seconds = 600
        calls = 0
        fail = False

        async def generate(self, description):
            self.calls += 1
            if self.fail:
                raise PortraitError("comfyui_unavailable")
            return ImageReply(data, "image/png", self.model, cost_known=True)

    class Translator:
        timeout_seconds = 20
        payloads = []

        async def translate(self, session, description, campaign_id=None):
            self.payloads.append(description)
            return description

    generator, translator = Generator(), Translator()
    client.app.state.campaign_cover_generator = generator
    client.app.state.campaign_cover_translator = translator
    client.app.state.campaign_cover_media_dir = tmp_path
    return cid, f"/api/campaigns/{cid}/cover", generator, translator, data


def test_owner_generates_once_replay_is_free_and_members_view(client, root, admin, cover_world):
    cid, url, generator, translator, data = cover_world
    assert client.get(url, headers=root).json()["status"] == "idle"
    first = client.post(url, headers=root, json={"request_key": "one"})
    assert first.status_code == 200, first.text
    art = first.json()
    assert art["status"] == "ready" and art["image_url"] and art["thumbnail_url"]
    assert client.post(url, headers=root, json={"request_key": "one"}).json() == art
    assert client.post(url, headers=root, json={"request_key": "two"}).json() == art
    assert generator.calls == 1
    assert set(translator.payloads[0]) == {"identity", "appearance", "personality"}
    assert "Туманные горы" in translator.payloads[0]["appearance"]
    player = register(client, invite(client, root, cid)["token"], "Зритель")
    assert client.get(art["image_url"], headers=player).content == data
    thumb = client.get(art["thumbnail_url"], headers=player)
    assert thumb.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(thumb.content)) as image:
        assert image.width <= 640 and image.height <= 360
    assert len(thumb.content) < len(data)
    assert client.get(art["image_url"]).status_code == 401
    assert client.get(art["image_url"], headers=admin).status_code == 404
    assert client.get(art["thumbnail_url"], headers=admin).status_code == 404


def test_players_and_outsiders_cannot_generate(client, root, admin, cover_world):
    cid, url, generator, _, _ = cover_world
    player = register(client, invite(client, root, cid)["token"], "Игрок")
    assert client.get(url, headers=player).json()["can_generate"] is False
    assert client.post(url, headers=player, json={"request_key": "p"}).status_code == 403
    assert client.post(url, headers=admin, json={"request_key": "o"}).status_code == 404
    assert generator.calls == 0


def test_failed_regeneration_keeps_the_ready_cover_and_failed_receipt_is_not_replayed(client, root, cover_world):
    _, url, generator, _, _ = cover_world
    before = client.post(url, headers=root, json={"request_key": "ok"}).json()["image_url"]
    generator.fail = True
    for _ in range(2):
        assert client.post(url, headers=root, json={"request_key": "bad", "regenerate": True}).status_code == 409
    assert generator.calls == 2  # the failed receipt is not replayed
    state = client.get(url, headers=root).json()
    assert state["image_url"] == before and state["status"] == "failed"
    assert client.get(before, headers=root).status_code == 200


def test_changed_intro_marks_cover_stale_until_explicit_regeneration(client, root, cover_world):
    cid, url, generator, _, _ = cover_world
    before = client.post(url, headers=root, json={"request_key": "ok"}).json()["image_url"]

    async def change(session):
        (await session.get(Campaign, cid)).public_intro = "Выжженная пустыня."

    db(client, change)
    assert client.get(url, headers=root).json()["stale"] is True
    assert client.post(url, headers=root, json={"request_key": "reuse"}).json()["image_url"] == before
    after = client.post(url, headers=root, json={"request_key": "new", "regenerate": True}).json()
    assert after["image_url"] != before and after["stale"] is False and generator.calls == 2


def test_cover_urls_in_room_and_home_projections(client, root, cover_world):
    cid, url, _, _, _ = cover_world
    room = client.get(f"/api/campaigns/{cid}", headers=root).json()
    assert room["cover_url"] is None and room["cover_thumbnail_url"] is None
    art = client.post(url, headers=root, json={"request_key": "ok"}).json()
    room = client.get(f"/api/campaigns/{cid}", headers=root).json()
    assert room["cover_url"] == art["image_url"] and room["cover_thumbnail_url"] == art["thumbnail_url"]
    card = next(c for c in client.get("/api/me/campaigns", headers=root).json() if c["id"] == cid)
    assert card["cover_url"] == art["image_url"] and card["cover_thumbnail_url"] == art["thumbnail_url"]


def test_world_without_intro_uses_name_and_unconfigured_generator_conflicts(client, root, cover_world):
    cid, url, generator, translator, _ = cover_world

    async def clear(session):
        (await session.get(Campaign, cid)).public_intro = ""

    db(client, clear)
    assert client.post(url, headers=root, json={"request_key": "named"}).status_code == 200
    assert translator.payloads[0]["appearance"] == "Тест"
    client.app.state.campaign_cover_generator = None
    state = client.get(url, headers=root).json()
    assert state["enabled"] is False and state["can_generate"] is False
    assert client.post(url, headers=root, json={"request_key": "none", "regenerate": True}).status_code == 409


def studio_world(client, root):
    from app.agents.llm import ScriptedLLM
    from tests.test_universal_studio import BASE, create, review_reply

    project = create(client, root)
    url = f"{BASE}/{project['id']}/studio"
    client.app.state.studio_llm = ScriptedLLM([review_reply()])
    rev = project["draft_revision"]
    assert client.post(url + "/review", headers=root, json={"expected_revision": rev}).status_code == 200
    version = client.post(url + "/accept", headers=root, json={"expected_revision": rev, "request_key": "v"}).json()[
        "id"
    ]
    return project, f"{BASE}/{project['id']}/cover", version


def test_world_cover_is_drawn_in_the_studio_from_public_text_only(client, root, admin, cover_world):
    _, _, generator, translator, data = cover_world
    project, url, _ = studio_world(client, root)
    assert client.get(url, headers=root).json()["status"] == "idle"
    art = client.post(url, headers=root, json={"request_key": "w1"}).json()
    assert art["status"] == "ready" and art["image_url"].startswith(f"{url}/")
    assert client.get(art["image_url"], headers=root).content == data
    assert client.get(art["thumbnail_url"], headers=root).headers["content-type"] == "image/webp"
    assert client.post(url, headers=root, json={"request_key": "w1"}).json() == art
    assert generator.calls == 1
    sent = str(translator.payloads)
    assert "A harbor awaits." in sent and "SECRET" not in sent
    assert client.get(url, headers=admin).status_code == 404
    assert client.post(url, headers=admin, json={"request_key": "x"}).status_code == 404


def test_launched_campaign_inherits_the_world_cover_until_it_draws_its_own(client, root, cover_world):
    _, _, generator, _, data = cover_world
    project, url, version = studio_world(client, root)
    world = client.post(url, headers=root, json={"request_key": "w1"}).json()
    options = {
        "name": "Game",
        "owner_plays": True,
        "tts_enabled": False,
        "master": {"type": "agent", "provider": "claude", "model": "x"},
    }
    launched = client.post(
        f"/api/adventures/{version}/games", headers=root, json={"options": options, "request_key": "g"}
    )
    assert launched.status_code == 201, launched.text
    cid = launched.json()["campaign_id"]
    image_id = world["image_url"].rsplit("/", 1)[-1]
    room = client.get(f"/api/campaigns/{cid}", headers=root).json()
    assert room["cover_url"] == f"/api/campaigns/{cid}/cover/{image_id}"
    card = next(c for c in client.get("/api/me/campaigns", headers=root).json() if c["id"] == cid)
    assert card["cover_thumbnail_url"] == room["cover_thumbnail_url"]
    assert client.get(room["cover_url"], headers=root).content == data
    assert client.get(room["cover_thumbnail_url"], headers=root).status_code == 200
    own_url = f"/api/campaigns/{cid}/cover"
    state = client.get(own_url, headers=root).json()
    assert state["inherited"] is True and state["image_url"] == room["cover_url"]
    own = client.post(own_url, headers=root, json={"request_key": "own"}).json()
    assert own["inherited"] is False and own["image_url"] != room["cover_url"]
    assert generator.calls == 2


def test_catalog_entry_shows_the_world_cover_thumbnail(client, root, admin, cover_world):
    project, url, version = studio_world(client, root)

    def entry():
        return next(
            e for e in client.get("/api/adventures/catalog", headers=root).json() if e["project_id"] == project["id"]
        )

    assert entry()["cover_thumbnail_url"] is None
    client.post(url, headers=root, json={"request_key": "w1"})
    thumb = entry()["cover_thumbnail_url"]
    assert thumb and thumb.startswith(f"/api/adventures/catalog/{project['id']}/cover/")
    response = client.get(thumb, headers=root)
    assert response.status_code == 200 and response.headers["content-type"] == "image/webp"
    assert client.get(thumb).status_code == 401
    assert client.get(thumb.replace(project["id"], "ap_missing"), headers=root).status_code == 404
    hidden = client.put(f"/api/author/projects/{project['id']}/catalog", headers=root, json={"listed": False})
    assert hidden.status_code == 200, hidden.text
    assert client.get(thumb, headers=root).status_code == 404
