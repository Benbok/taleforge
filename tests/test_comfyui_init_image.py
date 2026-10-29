import asyncio
import json

import httpx
import pytest

from app.agents.comfyui_portraits import ComfyUIPortraitGenerator
from app.agents.portraits import PortraitError
from app.config import ROOT
from tests.test_hero_portraits import PNG

MAP_WORKFLOW = ROOT / "content" / "workflows" / "map-backdrop-realvisxl-api.json"
LOCATION_WORKFLOW = ROOT / "content" / "workflows" / "location-realvisxl-api.json"


def responder(calls, *, upload_status=200):
    def respond(request):
        calls.append(request)
        if request.url.path == "/upload/image":
            if upload_status != 200:
                return httpx.Response(upload_status)
            return httpx.Response(200, json={"name": "bd.png", "subfolder": "", "type": "input"})
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "job1"})
        if request.url.path == "/history/job1":
            return httpx.Response(
                200,
                json={
                    "job1": {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {"9": {"images": [{"filename": "o.png", "subfolder": "", "type": "output"}]}},
                    }
                },
            )
        return httpx.Response(200, content=PNG, headers={"content-type": "image/png"})

    return respond


def generator(workflow, calls, **kw):
    return ComfyUIPortraitGenerator(
        workflow=workflow, transport=httpx.MockTransport(responder(calls, **kw)), poll_interval=0
    )


def test_init_image_is_uploaded_and_named_in_graph():
    calls = []
    reply = asyncio.run(generator(MAP_WORKFLOW, calls).generate({"appearance": "yard"}, init_image=PNG))
    assert reply.data == PNG
    paths = [r.url.path for r in calls]
    assert paths.count("/upload/image") == 1 and paths.count("/prompt") == 1
    assert paths.index("/upload/image") < paths.index("/prompt")
    graph = json.loads(next(r for r in calls if r.url.path == "/prompt").content)["prompt"]
    assert graph["10"]["inputs"]["image"] == "bd.png"
    assert graph["3"]["inputs"]["denoise"] <= 0.75


def test_upload_failure_never_submits_prompt():
    calls = []
    with pytest.raises(PortraitError) as error:
        asyncio.run(generator(MAP_WORKFLOW, calls, upload_status=500).generate({"appearance": "x"}, init_image=PNG))
    assert str(error.value) == "provider_error"
    assert not any(r.url.path == "/prompt" for r in calls)


def test_workflow_without_init_placeholder_rejects_image():
    calls = []
    with pytest.raises(PortraitError):
        asyncio.run(generator(LOCATION_WORKFLOW, calls).generate({"appearance": "x"}, init_image=PNG))
    assert not calls


def test_map_workflow_requires_an_image():
    calls = []
    with pytest.raises(PortraitError):
        asyncio.run(generator(MAP_WORKFLOW, calls).generate({"appearance": "x"}))
    assert not calls


def test_existing_workflow_still_works_without_image():
    calls = []
    reply = asyncio.run(generator(LOCATION_WORKFLOW, calls).generate({"appearance": "x"}))
    assert reply.data == PNG
    assert not any(r.url.path == "/upload/image" for r in calls)
