import asyncio
import json

import pytest

from app.agents.portraits import ImageReply, PortraitError
from app.core.world import get_scene
from app.db.models import Entity
from tests.test_api import invite, make_campaign, register
from tests.test_hero_portraits import PNG


def feature(entity_id, name, hidden=False):
    return {"id": "sf_" + entity_id, "entity_id": entity_id, "name": name, "kind": "object", "cells": [[1, 1, 1, 1]],
            "cover": "none", "hidden": hidden, "solid": False}


SKETCH = {"shape": "open", "cols": 10, "rows": 8, "party": [3, 3], "walls": [], "mask": None, "edges": [], "terrain": [],
          "material": "grass", "environment": "outdoor", "exits": [],
          "features": [feature("ic_stone", "Мшистый камень"), feature("ic_oak", "Старый дуб"),
                       feature("ic_secret", "SECRET-OBJECT", hidden=True), feature("ic_private", "SECRET-PRIVATE")]}


def db(client, function):
    async def run():
        async with client.app.state.sessionmaker() as session:
            result = await function(session)
            await session.commit()
            return result

    return asyncio.run(run())


@pytest.fixture
def icon_world(client, root, tmp_path):
    cid = make_campaign(client, root)["id"]

    async def setup(session):
        session.add_all([
            Entity(id="ic_room", campaign_id=cid, kind="location", name="Колея", description="Грунтовая дорога.",
                   state={"sketch": SKETCH}),
            Entity(id="ic_other", campaign_id=cid, kind="location", name="Другое", description="Иное место.", state={}),
            Entity(id="ic_stone", campaign_id=cid, kind="object", name="Мшистый камень", description="Старый валун, поросший мхом.",
                   location_id="ic_room", state={"gm_note": "SECRET-RUNES"}),
            Entity(id="ic_oak", campaign_id=cid, kind="object", name="Старый дуб", description="", location_id="ic_room", state={}),
            Entity(id="ic_secret", campaign_id=cid, kind="object", name="SECRET-OBJECT", description="SECRET-DESC",
                   location_id="ic_room", state={}),
            Entity(id="ic_private", campaign_id=cid, kind="object", name="SECRET-PRIVATE", description="SECRET-DESC",
                   location_id="ic_room", state={"visibility": "private"}),
            Entity(id="ic_elsewhere", campaign_id=cid, kind="object", name="Чужой предмет", description="x",
                   location_id="ic_other", state={}),
        ])
        (await get_scene(session, cid)).location_id = "ic_room"

    db(client, setup)

    class Generator:
        model = "comfyui/test"
        timeout_seconds = 600
        calls, fail = 0, False

        async def generate(self, description, **kw):
            self.calls += 1
            if self.fail:
                raise PortraitError("comfyui_unavailable")
            return ImageReply(PNG, "image/png", self.model, cost_known=True)

    class Translator:
        timeout_seconds = 20
        payloads = []

        async def translate(self, session, description, campaign_id=None):
            self.payloads.append(description)
            return {**description, "appearance": "A mossy boulder."}

    generator, translator = Generator(), Translator()
    translator.payloads = []
    client.app.state.object_icon_generator = generator
    client.app.state.object_icon_translator = translator
    client.app.state.object_icon_media_dir = tmp_path
    return cid, f"/api/campaigns/{cid}", generator, translator


def test_list_shows_only_public_objects_of_the_current_area(client, root, icon_world):
    cid, base, generator, _ = icon_world
    data = client.get(f"{base}/locations/ic_room/object-icons", headers=root).json()
    assert data["enabled"] is True and data["can_generate"] is True
    assert sorted(o["id"] for o in data["objects"]) == ["ic_oak", "ic_stone"]
    assert all(o["status"] == "idle" and o["image_url"] is None for o in data["objects"])
    assert "SECRET" not in json.dumps(data, ensure_ascii=False)
    assert client.get(f"{base}/locations/ic_other/object-icons", headers=root).status_code == 404
    assert generator.calls == 0


def test_admin_generates_an_icon_once_and_players_can_see_it(client, root, icon_world):
    cid, base, generator, translator = icon_world
    url = f"{base}/objects/ic_stone/icon"
    ready = client.post(url, headers=root, json={"request_key": "one"})
    assert ready.status_code == 200, ready.text
    image = ready.json()["image_url"]
    assert ready.json()["status"] == "ready" and image.startswith(url + "/")
    assert client.get(image, headers=root).content == PNG and client.get(image).status_code == 401
    assert client.post(url, headers=root, json={"request_key": "two"}).json()["image_url"] == image
    assert generator.calls == 1
    assert translator.payloads == [{"identity": "Мшистый камень", "appearance": "Старый валун, поросший мхом.", "personality": ""}]
    player = register(client, invite(client, root, cid)["token"], "Игрок")
    listed = {o["id"]: o for o in client.get(f"{base}/locations/ic_room/object-icons", headers=player).json()["objects"]}
    assert listed["ic_stone"]["image_url"] == image and listed["ic_stone"]["can_generate"] is False
    assert client.get(image, headers=player).content == PNG
    assert client.post(url, headers=player, json={"request_key": "p"}).status_code == 403
    assert generator.calls == 1


def test_hidden_private_and_foreign_objects_cannot_be_drawn_or_read(client, root, icon_world):
    _, base, generator, _ = icon_world
    for object_id in ("ic_secret", "ic_private", "ic_elsewhere", "ic_room", "nope"):
        response = client.post(f"{base}/objects/{object_id}/icon", headers=root, json={"request_key": "x" + object_id})
        assert response.status_code == 404, object_id
    image = client.post(f"{base}/objects/ic_stone/icon", headers=root, json={"request_key": "ok"}).json()["image_url"]
    assert client.get(image.replace("ic_stone", "ic_oak"), headers=root).status_code == 404
    assert generator.calls == 1


def test_disabled_reports_disabled_and_failure_keeps_the_object_without_an_icon(client, root, icon_world):
    _, base, generator, _ = icon_world
    generator.fail = True
    assert client.post(f"{base}/objects/ic_oak/icon", headers=root, json={"request_key": "bad"}).status_code == 409
    listed = {o["id"]: o for o in client.get(f"{base}/locations/ic_room/object-icons", headers=root).json()["objects"]}
    assert listed["ic_oak"]["image_url"] is None
    client.app.state.object_icon_generator = None
    data = client.get(f"{base}/locations/ic_room/object-icons", headers=root).json()
    assert data["enabled"] is False and data["can_generate"] is False
    assert client.post(f"{base}/objects/ic_oak/icon", headers=root, json={"request_key": "off"}).status_code == 409
