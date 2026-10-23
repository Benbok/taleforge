import asyncio
import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from tests.universal_helpers import create_hero

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")


def setup_generator(client, tmp_path):
    from app.agents.portraits import ImageReply

    class Fake:
        calls = 0
        model = "test-image"

        async def generate(self, description):
            self.calls += 1
            return ImageReply(PNG, "image/png", model=self.model)

    fake = Fake()
    client.app.state.portraits = fake
    client.app.state.portrait_media_dir = tmp_path
    return fake


def test_generate_replay_and_private_media(client, root, tmp_path):
    fake = setup_generator(client, tmp_path)
    hid = create_hero(client, root)
    url = f"/api/me/characters/{hid}/portrait"
    body = {"request_key": "first", "expected_revision": 1}
    result = client.post(url, headers=root, json=body)
    assert result.status_code == 200, result.text
    card = result.json()
    assert card["portrait_url"].startswith("/api/portraits/")
    assert card["revision"] == 1
    assert client.post(url, headers=root, json=body).json() == card
    assert fake.calls == 1
    assert client.get(card["portrait_url"]).status_code == 401
    media = client.get(card["portrait_url"], headers=root)
    assert media.status_code == 200 and media.content == PNG
    assert media.headers["content-type"] == "image/png"
    other = client.post("/api/auth/signup", json={"name": "other", "password": "password123"}).json()
    headers = {"Authorization": "Bearer " + other["token"]}
    assert client.get(card["portrait_url"], headers=headers).status_code == 404
    assert client.post(url, headers=headers, json={**body, "request_key": "foreign"}).status_code == 404
    assert fake.calls == 1


def test_failed_regeneration_keeps_previous_image(client, root, tmp_path):
    from app.agents.portraits import PortraitError

    fake = setup_generator(client, tmp_path)
    hid = create_hero(client, root)
    url = f"/api/me/characters/{hid}/portrait"
    before = client.post(url, headers=root, json={"request_key": "ok", "expected_revision": 1}).json()

    async def fail(description):
        fake.calls += 1
        raise PortraitError("provider_error")

    fake.generate = fail
    body = {"request_key": "fail", "expected_revision": 1}
    assert client.post(url, headers=root, json=body).status_code == 409
    assert client.post(url, headers=root, json=body).status_code == 409
    assert fake.calls == 2
    assert client.get(f"/api/me/characters/{hid}", headers=root).json() == before
    assert client.get(before["portrait_url"], headers=root).content == PNG


def test_copy_keeps_portrait_after_library_regeneration_and_deletion(client, root, tmp_path):
    from tests.test_api import make_campaign

    setup_generator(client, tmp_path)
    hid = create_hero(client, root)
    url = f"/api/me/characters/{hid}/portrait"
    first = client.post(url, headers=root, json={"request_key": "first", "expected_revision": 1}).json()
    campaign = make_campaign(client, root, owner_plays=True)
    cid = campaign["id"]
    copy = client.post(f"/api/campaigns/{cid}/characters/from-library/{hid}", headers=root).json()
    assert copy["portrait_url"] == first["portrait_url"]
    second = client.post(url, headers=root, json={"request_key": "second", "expected_revision": 1}).json()
    assert second["portrait_url"] != first["portrait_url"]
    client.delete(f"/api/me/characters/{hid}", headers=root)
    assert client.get(first["portrait_url"], headers=root).status_code == 200
    copy_url = f"/api/campaigns/{cid}/characters/{copy['id']}"
    assert client.get(copy_url, headers=root).json()["portrait_url"] == first["portrait_url"]
    generated = client.post(copy_url + "/portrait", headers=root, json={"request_key": "game", "expected_revision": 1})
    assert generated.status_code == 200, generated.text
    assert generated.json()["portrait_url"] != first["portrait_url"]
    assert generated.json()["sheet"] == copy["sheet"]


def test_overlap_and_stale_description_do_not_replace_portrait(client, root, tmp_path):
    from app.agents.portraits import ImageReply

    fake = setup_generator(client, tmp_path)
    hid = create_hero(client, root)
    entered, release = threading.Event(), threading.Event()

    async def slow(description):
        fake.calls += 1
        entered.set()
        assert await asyncio.to_thread(release.wait, 10)
        return ImageReply(PNG, "image/png", model=fake.model)

    fake.generate = slow
    url = f"/api/me/characters/{hid}"
    with ThreadPoolExecutor(1) as pool:
        running = pool.submit(
            client.post, url + "/portrait", headers=root, json={"request_key": "slow", "expected_revision": 1}
        )
        try:
            assert entered.wait(10)
            assert (
                client.post(
                    url + "/portrait", headers=root, json={"request_key": "duplicate", "expected_revision": 1}
                ).status_code
                == 409
            )
            assert fake.calls == 1
            edited = client.patch(
                url,
                headers=root,
                json={
                    "request_key": "edit",
                    "edit": {"expected_revision": 1, "description_patch": {"appearance": "Совсем новый образ"}},
                },
            )
            assert edited.status_code == 200, edited.text
        finally:
            release.set()
        assert running.result().status_code == 409
    assert client.get(url, headers=root).json()["portrait_url"] is None
    assert not list((tmp_path / "portraits").iterdir())


@pytest.mark.parametrize("status,content", [(429, {}), (200, {"status": "completed", "steps": []})])
def test_provider_failure_has_safe_reason_and_no_retry(status, content):
    from app.agents.portraits import GeminiPortraitGenerator, PortraitError

    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=content)

    generator = GeminiPortraitGenerator(
        "gemini-3.1-flash-lite-image", api_key="test-only", transport=httpx.MockTransport(respond)
    )
    with pytest.raises(PortraitError):
        asyncio.run(generator.generate({"identity": "Травница"}))
    assert len(calls) == 1


def test_provider_request_image_parsing_and_usage_accounting():
    from app.agents.portraits import GeminiPortraitGenerator

    def respond(request):
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["response_format"] == {
            "type": "image",
            "mime_type": "image/jpeg",
            "aspect_ratio": "1:1",
            "image_size": "1K",
        }
        assert "Травница" in body["input"]
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "steps": [
                    {
                        "type": "model_output",
                        "content": [
                            {"type": "image", "mime_type": "image/png", "data": base64.b64encode(PNG).decode()}
                        ],
                    }
                ],
                "usage": {"total_input_tokens": 100, "total_output_tokens": 1120, "total_thought_tokens": 10},
            },
        )

    generator = GeminiPortraitGenerator(
        "gemini-3.1-flash-lite-image", api_key="test-only", transport=httpx.MockTransport(respond)
    )
    reply = asyncio.run(generator.generate({"identity": "Травница"}))
    assert reply.data == PNG and reply.mime == "image/png"
    assert reply.cost_known and reply.cost == pytest.approx(0.03364)
    assert reply.tokens_in == 100 and reply.tokens_out == 1130


def test_unsafe_or_invalid_provider_image_cannot_be_published(client, root, tmp_path):
    from app.agents.portraits import ImageReply

    fake = setup_generator(client, tmp_path)

    async def invalid(description):
        return ImageReply(b'<svg onload="alert(1)">', "image/svg+xml", fake.model, cost=0.04, cost_known=True)

    fake.generate = invalid
    hid = create_hero(client, root)
    assert (
        client.post(
            f"/api/me/characters/{hid}/portrait", headers=root, json={"request_key": "invalid", "expected_revision": 1}
        ).status_code
        == 409
    )
    assert client.get(f"/api/me/characters/{hid}", headers=root).json()["portrait_url"] is None


def test_campaign_member_reads_but_cannot_regenerate_another_players_portrait(client, root, tmp_path):
    from tests.test_api import invite, make_campaign, register

    fake = setup_generator(client, tmp_path)
    hid = create_hero(client, root)
    first = client.post(
        f"/api/me/characters/{hid}/portrait", headers=root, json={"request_key": "first", "expected_revision": 1}
    ).json()
    campaign = make_campaign(client, root, owner_plays=True)
    cid = campaign["id"]
    copy = client.post(f"/api/campaigns/{cid}/characters/from-library/{hid}", headers=root).json()
    member = register(client, invite(client, root, cid)["token"], "Другой игрок")
    assert client.get(first["portrait_url"], headers=member).status_code == 200
    assert (
        client.post(
            f"/api/campaigns/{cid}/characters/{copy['id']}/portrait",
            headers=member,
            json={"request_key": "forbidden", "expected_revision": 1},
        ).status_code
        == 403
    )
    assert fake.calls == 1
    # A campaign participant does not gain access to the owner's newer library-only image.
    second = client.post(
        f"/api/me/characters/{hid}/portrait", headers=root, json={"request_key": "second", "expected_revision": 1}
    ).json()
    assert client.get(second["portrait_url"], headers=member).status_code == 404


def test_expired_generation_claim_can_be_replaced(client, root, tmp_path):
    from datetime import timedelta

    from app.db.models import HeroPortrait, LibraryCharacter, now

    fake = setup_generator(client, tmp_path)
    hid = create_hero(client, root)

    async def interrupted():
        async with client.app.state.sessionmaker() as session:
            job = HeroPortrait(
                id="hp_interrupted",
                owner_user_id=(await session.get(LibraryCharacter, hid)).owner_user_id,
                target_id=hid,
                request_key="interrupted",
                status="pending",
                created_at=now() - timedelta(minutes=4),
            )
            session.add(job)
            hero = await session.get(LibraryCharacter, hid)
            hero.portrait_job_id = job.id
            await session.commit()

    asyncio.run(interrupted())
    result = client.post(
        f"/api/me/characters/{hid}/portrait", headers=root, json={"request_key": "new-attempt", "expected_revision": 1}
    )
    assert result.status_code == 200, result.text
    assert fake.calls == 1
