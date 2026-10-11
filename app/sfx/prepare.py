"""First-start downloads only. Game-time inference remains offline and uses a fixed snapshot."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from app.config import Settings, _env

log = logging.getLogger(__name__)
REPO = "stabilityai/stable-audio-3-small-sfx"


def prepare(settings: Settings) -> None:
    from huggingface_hub import HfApi, snapshot_download

    folder = settings.sfx_model_dir
    manifest = folder / "manifest.json"
    if manifest.is_file():
        try:
            old = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("Invalid SFX manifest; rebuilding the local model view")
            old = {}
        if old.get("revision") == settings.sfx_model_revision and all(
            (folder / name).is_file() for name in ("model_config.json", "model.safetensors")
        ):
            log.info("SFX weights already prepared (%s); startup is offline", old["resolved_revision"])
            return
    folder.mkdir(parents=True, exist_ok=True)
    token = _env("HF_TOKEN")
    info = HfApi(token=token).model_info(REPO, revision=settings.sfx_model_revision)
    resolved = info.sha
    snapshot = Path(snapshot_download(REPO, revision=resolved, token=token))
    config = json.loads((snapshot / "model_config.json").read_text(encoding="utf-8"))

    def localize(value):
        if isinstance(value, list):
            for item in value:
                localize(item)
        elif isinstance(value, dict):
            if str(value.get("type", "")).lower() in ("t5gemma", "t5_gemma"):
                params = value.get("config", {})
                component = params.get("repo_id") or params.get("model_name") or "google/t5gemma-b-b-ul2"
                if component == REPO:
                    component_path = snapshot
                else:
                    component_path = Path(snapshot_download(component, token=token))
                # Keep the original model_name for the upstream architecture check, but read only local files.
                params["model_path"] = str(component_path)
                value["config"] = params
            for item in list(value.values()):
                localize(item)

    localize(config)
    # The persistent HF cache holds components; only the small config/checkpoint view is managed here.
    temp_config = folder / "model_config.json.tmp"
    temp_config.write_text(json.dumps(config), encoding="utf-8")
    checkpoint = folder / "model.safetensors"
    temporary = folder / "model.safetensors.tmp"
    temporary.unlink(missing_ok=True)
    try:
        # Snapshots are immutable; a hard link avoids storing the large checkpoint twice in one volume.
        os.link((snapshot / "model.safetensors").resolve(), temporary)
    except OSError:
        shutil.copyfile(snapshot / "model.safetensors", temporary)
    os.replace(temporary, checkpoint)
    os.replace(temp_config, folder / "model_config.json")
    temp_manifest = folder / "manifest.json.tmp"
    temp_manifest.write_text(
        json.dumps({"revision": settings.sfx_model_revision, "resolved_revision": resolved, "repo": REPO}),
        encoding="utf-8",
    )
    os.replace(temp_manifest, manifest)
    log.info("SFX model ready: %s@%s", REPO, resolved)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    prepare(Settings.from_env())
