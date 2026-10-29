"""Local ComfyUI adapter: one submission, bounded polling and download, no cloud fallback."""

import asyncio
import json
import secrets
from pathlib import Path

import httpx

from app.agents.portraits import MAX_IMAGE_BYTES, ImageReply, PortraitError, validate_image
from app.config import ROOT

DEFAULT_WORKFLOW = ROOT / "content" / "workflows" / "portrait-realvisxl-api.json"
FANTASY_ART_DIRECTION = (
    "Hand-painted fantasy illustration, stylized painterly shapes, visible brush strokes, "
    "atmospheric light, rich muted colors. "
)


class ComfyUIPortraitGenerator:
    def __init__(
        self,
        base_url="http://127.0.0.1:8188",
        workflow=DEFAULT_WORKFLOW,
        *,
        timeout_seconds=600,
        transport=None,
        poll_interval=1.0,
        style=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.poll_interval = poll_interval
        self.style = style
        self.workflow = json.loads(Path(workflow).read_text(encoding="utf-8"))
        self.output_nodes = [k for k, v in self.workflow.items() if v.get("class_type") == "SaveImage"]
        if not self.output_nodes or "{{prompt}}" not in json.dumps(self.workflow):
            raise ValueError("ComfyUI workflow must be API format with SaveImage and {{prompt}}")
        checkpoint = next(
            (
                v["inputs"]["ckpt_name"]
                for v in self.workflow.values()
                if v.get("class_type") == "CheckpointLoaderSimple"
            ),
            "workflow",
        )
        self.model = f"comfyui/{checkpoint}"
        self.needs_init_image = "{{init_image}}" in json.dumps(self.workflow)

    async def generate(self, description: dict, *, init_image: bytes | None = None) -> ImageReply:
        # Art direction leads; observed appearance follows before the composition instructions.
        details = ", ".join(str(description.get(k) or "") for k in ("appearance", "identity", "personality"))
        style = self.style or (
            "Painted fantasy character portrait, head and shoulders, centered face, "
            "room around head for circular crop, expressive eyes, soft cinematic lighting, "
            "restrained background, detailed illustrated game art, no text."
        )
        seed = secrets.randbits(63)
        if bool(init_image) != self.needs_init_image:
            raise PortraitError("provider_error")
        image_name = f"taleforge-{secrets.token_hex(8)}.png"

        def substitute(value):
            if value == "{{seed}}":
                return seed
            if isinstance(value, str):
                return value.replace("{{prompt}}", prompt).replace("{{init_image}}", image_name)
            if isinstance(value, dict):
                return {k: substitute(v) for k, v in value.items()}
            if isinstance(value, list):
                return [substitute(v) for v in value]
            return value

        prompt_id = None
        finished = False
        async with httpx.AsyncClient(base_url=self.base_url + "/", timeout=30, transport=self.transport) as client:
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    prompt = f"{FANTASY_ART_DIRECTION}{details}. {style}"
                    if init_image:
                        upload = await client.post(
                            "upload/image",
                            files={"image": (image_name, init_image, "image/png")},
                            data={"overwrite": "true", "type": "input"},
                        )
                        upload.raise_for_status()
                        image_name = upload.json()["name"]
                    response = await client.post("prompt", json={"prompt": substitute(self.workflow)})
                    response.raise_for_status()
                    prompt_id = response.json()["prompt_id"]
                    while True:
                        response = await client.get(f"history/{prompt_id}")
                        response.raise_for_status()
                        job = response.json().get(prompt_id, {})
                        status = job.get("status") or {}
                        if status.get("status_str") == "error":
                            raise PortraitError("comfyui_execution_error")
                        if status.get("completed"):
                            images = [
                                image
                                for node in self.output_nodes
                                for image in job.get("outputs", {}).get(node, {}).get("images", [])
                                if image.get("type") == "output"
                            ]
                            if len(images) != 1:
                                raise PortraitError("no_image")
                            image = images[0]
                            async with client.stream(
                                "GET",
                                "view",
                                params={
                                    "filename": image["filename"],
                                    "subfolder": image.get("subfolder", ""),
                                    "type": "output",
                                },
                            ) as response:
                                response.raise_for_status()
                                data = bytearray()
                                async for chunk in response.aiter_bytes():
                                    data.extend(chunk)
                                    if len(data) > MAX_IMAGE_BYTES:
                                        raise PortraitError("invalid_image")
                                mime = response.headers.get("content-type", "").split(";")[0].strip()
                            validate_image(bytes(data), mime)
                            finished = True
                            return ImageReply(bytes(data), mime, self.model, cost=0, cost_known=True)
                        await asyncio.sleep(self.poll_interval)
            except TimeoutError as exc:
                raise PortraitError("comfyui_timeout") from exc
            except httpx.ConnectError as exc:
                raise PortraitError("comfyui_unavailable") from exc
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                raise PortraitError("provider_error") from exc
            finally:
                if prompt_id and not finished:
                    # Also clean up after transport failures/cancellation, without interrupting running work.
                    try:
                        async with asyncio.timeout(5):
                            await client.post("queue", json={"delete": [prompt_id]}, timeout=5)
                    except (httpx.HTTPError, TimeoutError):
                        pass
