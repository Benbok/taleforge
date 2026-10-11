"""Replaceable inference interface. Heavy dependencies are imported only by the renderer process."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol


class SfxBackend(Protocol):
    def generate(self, parameters: dict, seed: int, destination: Path) -> None: ...


class StableAudioBackend:
    def __init__(self, model_dir: Path, device: str = "cpu", threads: int = 2):
        self.model_dir, self.device, self.threads = model_dir, device, threads

    def generate(self, parameters: dict, seed: int, destination: Path) -> None:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import soundfile as sf
        import torch
        from stable_audio_3 import StableAudioModel
        from stable_audio_3.model_configs import all_models

        if self.device not in ("cpu", "cuda"):
            raise ValueError("SFX_DEVICE должен быть cpu или cuda")
        if parameters["model"] != "small-sfx":
            raise ValueError("этот адаптер поддерживает только small-sfx")
        manifest_path = self.model_dir / "manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError("веса SFX не подготовлены: дождитесь загрузки контейнера sfx")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["revision"] != parameters["revision"]:
            raise RuntimeError("версия весов SFX отличается от SFX_MODEL_REVISION")
        if manifest["resolved_revision"] != parameters["weights_digest"]:
            raise RuntimeError("контрольная версия локальных весов SFX изменилась")
        config, checkpoint = self.model_dir / "model_config.json", self.model_dir / "model.safetensors"
        if not config.is_file() or not checkpoint.is_file():
            raise RuntimeError("локальные веса SFX отсутствуют")

        class LocalModel:
            def resolve(self):
                return str(config), str(checkpoint)

        all_models["small-sfx"] = LocalModel()
        torch.set_num_threads(self.threads)
        torch.set_num_interop_threads(1)
        model = StableAudioModel.from_pretrained("small-sfx", device=self.device, model_half=self.device == "cuda")
        prompt = parameters["description"]
        if parameters.get("context"):
            prompt += ". " + parameters["context"]
        prompt += ". Sound effect only. No speech, no music."
        result = model.generate(
            prompt=prompt,
            duration=parameters["duration_seconds"],
            seed=seed,
            steps=parameters["steps"],
            cfg_scale=1.0,
        )
        waveform = result[0].detach().float().cpu().numpy().T
        # No NaN/Inf samples or huge outputs can reach the audio converter.
        import numpy as np

        if waveform.ndim != 2 or waveform.shape[1] not in (1, 2) or not np.isfinite(waveform).all():
            raise ValueError("модель вернула неверные аудиоданные")
        sr = int(model.model_config["sample_rate"])
        waveform = waveform[: round(parameters["duration_seconds"] * sr)]
        sf.write(destination, np.clip(waveform, -1, 1), sr, subtype="PCM_16", format="WAV")
