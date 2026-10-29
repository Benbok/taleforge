import asyncio
import json

import httpx
import pytest

from tests.test_hero_portraits import PNG


def test_local_job_waits_for_its_output_and_keeps_seed_and_description_local():
    from app.agents.comfyui_portraits import ComfyUIPortraitGenerator

    calls = []
    polls = 0

    def respond(request):
        nonlocal polls
        calls.append(request)
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/prompt":
            graph = json.loads(request.content)["prompt"]
            assert "silver hair" in graph["6"]["inputs"]["text"]
            assert graph["6"]["inputs"]["text"].startswith("Hand-painted fantasy illustration")
            assert "photorealistic" in graph["7"]["inputs"]["text"]
            assert isinstance(graph["3"]["inputs"]["seed"], int)
            assert graph["4"]["inputs"]["ckpt_name"] == "RealVisXL_V5.0_fp16.safetensors"
            return httpx.Response(200, json={"prompt_id": "job1"})
        if request.url.path == "/history/job1":
            polls += 1
            if polls == 1:
                return httpx.Response(200, json={})
            return httpx.Response(
                200,
                json={
                    "job1": {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {"9": {"images": [{"filename": "portrait.png", "subfolder": "", "type": "output"}]}},
                    }
                },
            )
        assert request.url.path == "/view" and request.url.params["filename"] == "portrait.png"
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    generator = ComfyUIPortraitGenerator(transport=httpx.MockTransport(respond), poll_interval=0)
    reply = asyncio.run(generator.generate({"appearance": "silver hair", "identity": "forest ranger"}))
    assert reply.data == PNG and reply.mime == "image/png"
    assert reply.cost_known and reply.cost == 0
    assert sum(r.url.path == "/prompt" for r in calls) == 1


@pytest.mark.parametrize("mode", ["rejected", "execution_error", "unavailable", "invalid_image"])
def test_local_failure_is_bounded_and_never_resubmits(mode):
    from app.agents.comfyui_portraits import ComfyUIPortraitGenerator
    from app.agents.portraits import PortraitError

    submitted = []

    def respond(request):
        if mode == "unavailable":
            raise httpx.ConnectError("offline", request=request)
        if request.url.path == "/prompt":
            submitted.append(request)
            return httpx.Response(400 if mode == "rejected" else 200, json={"prompt_id": "job1"})
        if request.url.path.startswith("/history/"):
            if mode == "execution_error":
                return httpx.Response(200, json={"job1": {"status": {"status_str": "error", "completed": False}}})
            return httpx.Response(
                200,
                json={
                    "job1": {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {"9": {"images": [{"filename": "bad.png", "type": "output"}]}},
                    }
                },
            )
        return httpx.Response(200, content=b"not an image", headers={"content-type": "image/png"})

    generator = ComfyUIPortraitGenerator(transport=httpx.MockTransport(respond), poll_interval=0)
    with pytest.raises(PortraitError):
        asyncio.run(generator.generate({"appearance": "ranger"}))
    assert len(submitted) <= 1


def test_timeout_removes_only_own_queued_job_without_global_interrupt():
    from app.agents.comfyui_portraits import ComfyUIPortraitGenerator
    from app.agents.portraits import PortraitError

    calls = []

    def respond(request):
        calls.append((request.url.path, request.content))
        return httpx.Response(200, json={"prompt_id": "job1"} if request.url.path == "/prompt" else {})

    generator = ComfyUIPortraitGenerator(transport=httpx.MockTransport(respond), timeout_seconds=0.03, poll_interval=1)
    with pytest.raises(PortraitError, match="timeout"):
        asyncio.run(generator.generate({"appearance": "ranger"}))
    assert ("/queue", b'{"delete":["job1"]}') in calls
    assert not any(path == "/interrupt" for path, _ in calls)


def test_settings_select_local_generator_and_keep_cloud_default(monkeypatch):
    from app.agents.portraits import GeminiPortraitGenerator, create_portrait_generator
    from app.config import Settings

    assert isinstance(create_portrait_generator(Settings()), GeminiPortraitGenerator)
    monkeypatch.setenv("PORTRAIT_PROVIDER", "comfyui")
    monkeypatch.setenv("PORTRAIT_COMFYUI_URL", "http://127.0.0.1:8188")
    monkeypatch.setenv("PORTRAIT_COMFYUI_TIMEOUT_SEC", "600")
    local = create_portrait_generator(Settings.from_env())
    assert local.model.startswith("comfyui/") and local.timeout_seconds == 600
    with pytest.raises(ValueError, match="PORTRAIT_PROVIDER"):
        create_portrait_generator(Settings(portrait_provider="typo"))


def test_local_queue_claim_does_not_expire_after_cloud_deadline(client, root, tmp_path):
    from datetime import timedelta

    from app.db.models import HeroPortrait, LibraryCharacter, now
    from tests.test_hero_portraits import setup_generator
    from tests.universal_helpers import create_hero

    fake = setup_generator(client, tmp_path)
    fake.timeout_seconds = 600
    hero_id = create_hero(client, root)

    async def queue_job():
        async with client.app.state.sessionmaker() as session:
            hero = await session.get(LibraryCharacter, hero_id)
            session.add(
                HeroPortrait(
                    id="hp_local_pending",
                    owner_user_id=hero.owner_user_id,
                    target_id=hero_id,
                    request_key="local-running",
                    status="pending",
                    created_at=now() - timedelta(minutes=4),
                )
            )
            hero.portrait_job_id = "hp_local_pending"
            await session.commit()

    asyncio.run(queue_job())
    result = client.post(
        f"/api/me/characters/{hero_id}/portrait",
        headers=root,
        json={"request_key": "second-local", "expected_revision": 1},
    )
    assert result.status_code == 409 and result.json()["detail"]["code"] == "portrait_pending"
    assert fake.calls == 0


@pytest.mark.parametrize("cancel", [False, True])
def test_submitted_job_is_removed_when_polling_fails_or_request_is_cancelled(cancel):
    from app.agents.comfyui_portraits import ComfyUIPortraitGenerator
    from app.agents.portraits import PortraitError

    deleted = []

    async def run():
        polling = asyncio.Event()

        async def respond(request):
            if request.url.path == "/prompt":
                return httpx.Response(200, json={"prompt_id": "queued-job"})
            if request.url.path == "/queue":
                deleted.append(json.loads(request.content)["delete"])
                return httpx.Response(200, json={})
            polling.set()
            if cancel:
                await asyncio.Event().wait()
            raise httpx.ReadTimeout("poll timeout", request=request)

        generator = ComfyUIPortraitGenerator(transport=httpx.MockTransport(respond))
        task = asyncio.create_task(generator.generate({"appearance": "ranger"}))
        if cancel:
            await polling.wait()
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else PortraitError):
            await task

    asyncio.run(run())
    assert deleted == [["queued-job"]]
