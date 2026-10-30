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
    uploads = []

    def respond(request):
        calls.append(request)
        if request.url.path == "/upload/image":
            if upload_status != 200:
                return httpx.Response(upload_status)
            uploads.append(request)
            return httpx.Response(200, json={"name": f"up{len(uploads)}.png", "subfolder": "", "type": "input"})
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
    assert paths.count("/upload/image") == 2 and paths.count("/prompt") == 1  # outline + a neutral control image
    assert paths.index("/upload/image") < paths.index("/prompt")
    graph = json.loads(next(r for r in calls if r.url.path == "/prompt").content)["prompt"]
    assert graph["10"]["inputs"]["image"] == "up1.png"
    assert 0.5 <= graph["3"]["inputs"]["denoise"] <= 1.0  # ControlNet carries the layout, so the sampler can repaint almost fully
    assert graph["4"]["inputs"]["ckpt_name"].startswith("DreamShaperXL_Turbo")
    lora = graph["20"]["inputs"]
    assert lora["lora_name"].startswith("Og_VTT_Maps") and 0.3 <= lora["strength_model"] <= 1.0
    assert graph["3"]["inputs"]["model"] == ["20", 0] and graph["6"]["inputs"]["clip"] == ["20", 1]
    assert graph["7"]["inputs"]["clip"] == ["20", 1]
    assert graph["3"]["inputs"]["steps"] <= 12 and graph["3"]["inputs"]["cfg"] <= 3


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


def test_control_image_is_uploaded_second_and_wired_into_controlnet():
    calls = []
    asyncio.run(generator(MAP_WORKFLOW, calls).generate({"appearance": "x"}, init_image=PNG, control_image=PNG))
    assert [r.url.path for r in calls].count("/upload/image") == 2
    graph = json.loads(next(r for r in calls if r.url.path == "/prompt").content)["prompt"]
    assert graph["10"]["inputs"]["image"] == "up1.png" and graph["30"]["inputs"]["image"] == "up2.png"
    assert graph["32"]["inputs"]["strength"] > 0
    assert graph["3"]["inputs"]["positive"] == ["32", 0] and graph["3"]["inputs"]["negative"] == ["32", 1]
    assert graph["31"]["inputs"]["control_net_name"].startswith("controlnet-scribble-sdxl")


def test_missing_control_image_switches_the_controlnet_off():
    calls = []
    asyncio.run(generator(MAP_WORKFLOW, calls).generate({"appearance": "x"}, init_image=PNG))
    graph = json.loads(next(r for r in calls if r.url.path == "/prompt").content)["prompt"]
    assert graph["32"]["inputs"]["strength"] == 0.0 and graph["30"]["inputs"]["image"].startswith("up")


def test_control_image_for_a_workflow_without_controlnet_is_rejected():
    calls = []
    with pytest.raises(PortraitError):
        asyncio.run(generator(LOCATION_WORKFLOW, calls).generate({"appearance": "x"}, control_image=PNG))
    assert not calls


def test_control_style_is_added_to_the_prompt_only_when_a_control_image_is_given():
    def prompt_of(calls):
        graph = json.loads(next(r for r in calls if r.url.path == "/prompt").content)["prompt"]
        return graph["6"]["inputs"]["text"]

    with_control, without = [], []
    kw = dict(workflow=MAP_WORKFLOW, poll_interval=0, control_style="ROADS-SENTENCE. ")
    asyncio.run(ComfyUIPortraitGenerator(transport=httpx.MockTransport(responder(with_control)), **kw).generate(
        {"appearance": "yard"}, init_image=PNG, control_image=PNG))
    asyncio.run(ComfyUIPortraitGenerator(transport=httpx.MockTransport(responder(without)), **kw).generate(
        {"appearance": "yard"}, init_image=PNG))
    assert "ROADS-SENTENCE" in prompt_of(with_control) and "ROADS-SENTENCE" not in prompt_of(without)


def test_control_style_can_be_overridden_per_call():
    calls = []
    gen = ComfyUIPortraitGenerator(workflow=MAP_WORKFLOW, poll_interval=0, control_style="DEFAULT-STYLE. ",
                                   transport=httpx.MockTransport(responder(calls)))
    asyncio.run(gen.generate({"appearance": "x"}, init_image=PNG, control_image=PNG, control_style="OVERRIDE-STYLE. "))
    prompt = json.loads(next(r for r in calls if r.url.path == "/prompt").content)["prompt"]["6"]["inputs"]["text"]
    assert "OVERRIDE-STYLE" in prompt and "DEFAULT-STYLE" not in prompt
