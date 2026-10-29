import asyncio
import io
import json

import pytest
from PIL import Image

from app.agents.portraits import ImageReply, PortraitError
from app.core.world import get_scene
from app.db.models import Entity
from tests.test_api import invite, make_campaign, register
from tests.test_hero_portraits import PNG

SKETCH = {
    "shape": "open", "cols": 10, "rows": 8, "party": [3, 3], "walls": [], "mask": None, "edges": [],
    "terrain": [{"kind": "road", "cells": [[4, 0, 4, 7]]}], "material": "grass", "environment": "outdoor",
    "exits": [
        {"name": "Дверь", "side": "n", "at": 5, "kind": "door"},
        {"name": "Тайный ход", "side": "w", "at": 2, "kind": "door", "hidden": True},
    ],
    "features": [{"name": "SECRET-TRAP", "kind": "object", "cells": [[2, 2, 2, 2]], "hidden": True}],
}


def db(client, function):
    async def run():
        async with client.app.state.sessionmaker() as session:
            result = await function(session)
            await session.commit()
            return result

    return asyncio.run(run())


@pytest.fixture
def backdrop_world(client, root, tmp_path):
    cid = make_campaign(client, root)["id"]

    async def setup(session):
        session.add_all(
            [
                Entity(id="bd_room", campaign_id=cid, kind="location", name="Двор",
                       description="Двор таверны.", state={"secret": "SECRET-RUINS", "sketch": SKETCH}),
                Entity(id="bd_bare", campaign_id=cid, kind="location", name="Голое место", description="Пусто.", state={}),
                Entity(id="bd_hidden", campaign_id=cid, kind="location", name="SECRET-ROOM",
                       description="SECRET-TREASURE", state={"sketch": SKETCH}),
            ]
        )
        (await get_scene(session, cid)).location_id = "bd_room"

    db(client, setup)

    class Generator:
        model = "comfyui/test"
        timeout_seconds = 600
        calls, fail, inits = 0, False, []

        async def generate(self, description, *, init_image=None):
            self.calls += 1
            self.inits.append(init_image)
            if self.fail:
                raise PortraitError("comfyui_unavailable")
            return ImageReply(PNG, "image/png", self.model, cost_known=True)

    class Translator:
        timeout_seconds = 20
        payloads = []

        async def translate(self, session, description, campaign_id=None):
            self.payloads.append(description)
            return {**description, "appearance": "Tavern yard."}

    generator, translator = Generator(), Translator()
    generator.inits, translator.payloads = [], []
    client.app.state.map_backdrop_generator = generator
    client.app.state.map_backdrop_translator = translator
    client.app.state.map_backdrop_media_dir = tmp_path
    return cid, f"/api/campaigns/{cid}/locations/bd_room/map-backdrop", generator, translator


def test_admin_owner_generates_once_and_players_can_view(client, root, backdrop_world):
    cid, url, generator, translator = backdrop_world
    status = client.get(url, headers=root).json()
    assert status["status"] == "idle" and status["enabled"] is True and status["can_generate"] is True
    assert generator.calls == 0
    ready = client.post(url, headers=root, json={"request_key": "one"})
    assert ready.status_code == 200, ready.text
    image = ready.json()["image_url"]
    assert ready.json()["status"] == "ready" and image.startswith(url + "/")
    assert client.get(image, headers=root).content == PNG
    assert client.get(image).status_code == 401
    assert client.post(url, headers=root, json={"request_key": "two"}).json()["image_url"] == image
    assert generator.calls == 1
    player = register(client, invite(client, root, cid)["token"], "Игрок")
    seen = client.get(url, headers=player).json()
    assert seen["image_url"] == image and seen["can_generate"] is False
    assert client.get(image, headers=player).content == PNG
    assert client.post(url, headers=player, json={"request_key": "p"}).status_code == 403
    assert generator.calls == 1


def test_hidden_secrets_never_reach_translator_or_skeleton(client, root, backdrop_world):
    _, url, generator, translator = backdrop_world
    assert client.post(url, headers=root, json={"request_key": "one"}).status_code == 200
    assert "SECRET" not in json.dumps(translator.payloads, ensure_ascii=False)
    assert translator.payloads[0]["appearance"] == "Двор таверны."
    init = Image.open(io.BytesIO(generator.inits[0]))
    assert init.size == (768, 640)


def test_disabled_flag_reports_disabled_and_rejects(client, root, backdrop_world):
    _, url, generator, _ = backdrop_world
    client.app.state.map_backdrop_generator = None
    status = client.get(url, headers=root).json()
    assert status["enabled"] is False and status["can_generate"] is False
    assert client.post(url, headers=root, json={"request_key": "one"}).status_code == 409
    assert generator.calls == 0


def test_unseen_or_foreign_area_is_404(client, root, backdrop_world):
    _, url, generator, _ = backdrop_world
    hidden = url.replace("bd_room", "bd_hidden")
    assert client.get(hidden, headers=root).status_code == 404
    assert client.post(hidden, headers=root, json={"request_key": "x"}).status_code == 404
    assert client.get(url.replace("bd_room", "nope"), headers=root).status_code == 404
    assert generator.calls == 0


def test_failed_refresh_keeps_previous_image(client, root, backdrop_world):
    _, url, generator, _ = backdrop_world
    before = client.post(url, headers=root, json={"request_key": "ok"}).json()["image_url"]
    generator.fail = True
    assert client.post(url, headers=root, json={"request_key": "bad", "regenerate": True}).status_code == 409
    assert client.get(url, headers=root).json()["image_url"] == before
    assert client.get(before, headers=root).content == PNG


def test_changed_description_marks_stale(client, root, backdrop_world):
    _, url, _, _ = backdrop_world
    client.post(url, headers=root, json={"request_key": "ok"})

    async def change(session):
        (await session.get(Entity, "bd_room")).description = "Идёт снег."

    db(client, change)
    assert client.get(url, headers=root).json()["stale"] is True


def test_revealing_a_hidden_exit_marks_stale_but_keeps_serving_old_file(client, root, backdrop_world):
    _, url, _, _ = backdrop_world
    image = client.post(url, headers=root, json={"request_key": "ok"}).json()["image_url"]

    async def reveal(session):
        row = await session.get(Entity, "bd_room")
        sketch = json.loads(json.dumps(row.state["sketch"]))
        sketch["exits"][1]["hidden"] = False
        row.state = {**row.state, "sketch": sketch}

    db(client, reveal)
    assert client.get(url, headers=root).json()["stale"] is True
    assert client.get(image, headers=root).content == PNG


def test_missing_sketch_blocks_generation(client, root, backdrop_world):
    cid, url, generator, _ = backdrop_world

    async def move(session):
        (await get_scene(session, cid)).location_id = "bd_bare"

    db(client, move)
    bare = url.replace("bd_room", "bd_bare")
    assert client.get(bare, headers=root).json()["can_generate"] is False
    response = client.post(bare, headers=root, json={"request_key": "x"})
    assert response.status_code == 409 and "схему" in response.text
    assert generator.calls == 0


def test_party_moving_away_does_not_leak_files_of_previous_area(client, root, backdrop_world):
    cid, url, _, _ = backdrop_world
    image = client.post(url, headers=root, json={"request_key": "ok"}).json()["image_url"]

    async def move(session):
        (await get_scene(session, cid)).location_id = "bd_bare"

    db(client, move)
    assert client.get(image, headers=root).status_code == 404
