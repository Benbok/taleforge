"""One bounded subprocess per inference: RAM/GPU is released even on timeout."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

from app.sfx.backend import StableAudioBackend
from app.sfx.storage import encode_wav


def main() -> None:
    spec = json.load(sys.stdin)
    # Independent watchdog prevents orphan inference after a coordinator/container crash.
    timer = threading.Timer(spec["timeout"], lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    output = Path(spec["output"])
    try:
        if spec["parameters"]["backend"] != "stable-audio-3":
            raise ValueError("неизвестный SFX backend")
        with tempfile.TemporaryDirectory(prefix="sfx-") as folder:
            wav = Path(folder) / "render.wav"
            backend = StableAudioBackend(Path(spec["model_dir"]), spec["parameters"]["device"], spec["threads"])
            backend.generate(spec["parameters"], spec["seed"], wav)
            result = encode_wav(wav, output, spec["parameters"]["duration_seconds"])
        # A separate JSON result file avoids mixing the contract with model progress output.
        Path(spec["result"]).write_text(json.dumps(result), encoding="utf-8")
    except Exception as exc:
        token = os.environ.get("HF_TOKEN", "")
        message = str(exc).replace(token, "[redacted]") if token else str(exc)
        print(f"{type(exc).__name__}: {message[:500]}", file=sys.stderr)
        sys.exit(1)
    finally:
        timer.cancel()


if __name__ == "__main__":
    main()
