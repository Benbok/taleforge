"""Read-only model access diagnostic. Never prints credentials or response bodies."""

import asyncio

import httpx

from app.config import _env


async def main():
    token = _env("HF_TOKEN")
    if not token:
        print("HF_TOKEN отсутствует")
        return
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        url = "https://huggingface.co/stabilityai/stable-audio-3-small-sfx/resolve/main/model_config.json"
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        print(f"Stable Audio 3 Small-SFX: HTTP {response.status_code}")
        if response.status_code == 200:
            config = response.json()
            components = set()

            def walk(value):
                if isinstance(value, dict):
                    if str(value.get("type", "")).lower() in ("t5gemma", "t5_gemma"):
                        params = value.get("config", {})
                        components.add(
                            (
                                params.get("repo_id") or params.get("model_name") or "google/t5gemma-b-b-ul2",
                                params.get("subfolder", ""),
                            )
                        )
                    for item in value.values():
                        walk(item)
                elif isinstance(value, list):
                    for item in value:
                        walk(item)

            walk(config)
            for component, subfolder in sorted(components):
                filename = f"{subfolder}/config.json" if subfolder else "config.json"
                check = await client.get(
                    f"https://huggingface.co/{component}/resolve/main/{filename}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                print(f"Text encoder {component}/{subfolder}: HTTP {check.status_code}")


if __name__ == "__main__":
    asyncio.run(main())
