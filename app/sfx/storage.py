"""Server-owned immutable OGG files; no paths supplied by the model or browser."""

from __future__ import annotations

import array
import hashlib
import math
import os
import re
import subprocess
import sys
import wave
from pathlib import Path

from app.config import Settings

MAX_ASSET_BYTES = 2 * 1024 * 1024


def asset_path(settings: Settings, asset_id: str) -> Path:
    if not re.fullmatch(r"sa_[a-f0-9]{16}", asset_id):
        raise ValueError("недопустимый идентификатор звука")
    root = (settings.audio_dir / "generated").resolve()
    path = (root / f"{asset_id}.ogg").resolve()
    if path.parent != root:
        raise ValueError("недопустимый путь звука")
    return path


def validate_wav(path: Path, expected_duration: float) -> float:
    if path.stat().st_size > MAX_ASSET_BYTES:
        raise ValueError("слишком большой WAV")
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() not in (1, 2) or not 16000 <= w.getframerate() <= 48000:
            raise ValueError("ожидался PCM16 WAV, mono/stereo, 16–48 kHz")
        duration = w.getnframes() / w.getframerate()
        if not 0.99 <= duration <= 4.01 or abs(duration - expected_duration) > 0.05:
            raise ValueError("неверная длительность звука")
        samples = array.array("h", w.readframes(w.getnframes()))
        if len(samples) != w.getnframes() * w.getnchannels():
            raise ValueError("обрезанный WAV")
    if sys.byteorder != "little":
        samples.byteswap()
    peak = max((abs(x) for x in samples), default=0)
    if peak < 8:
        raise ValueError("генератор вернул тишину")
    return duration


def encode_wav(wav: Path, output: Path, duration: float) -> dict:
    measured = validate_wav(wav, duration)
    # Limiter and attenuation bound true playback peaks; explicit format permits .tmp filenames.
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(wav),
            "-t",
            str(duration),
            "-af",
            "alimiter=limit=0.89:level=false,volume=0.8",
            "-ar",
            "48000",
            "-c:a",
            "libopus",
            "-b:a",
            "96k",
            "-f",
            "ogg",
            str(output),
        ],
        check=True,
        timeout=30,
        capture_output=True,
    )
    data = output.read_bytes()
    if not data.startswith(b"OggS") or not 32 <= len(data) <= MAX_ASSET_BYTES:
        raise ValueError("неверный OGG/Opus результат")
    if not math.isfinite(measured):
        raise ValueError("неверная длительность")
    # Windows FlushFileBuffers requires a writable descriptor, unlike POSIX fsync.
    with output.open("rb+") as f:
        os.fsync(f.fileno())
    return {"duration_seconds": measured, "size_bytes": len(data), "digest": hashlib.sha256(data).hexdigest()}


def sweep_orphans(settings: Settings, known: set[str], older_than: float) -> int:
    root = (settings.audio_dir / "generated").resolve()
    if not root.is_dir():
        return 0
    removed = 0
    for candidate in root.iterdir():
        match = re.fullmatch(r"(sa_[a-f0-9]{16})\.ogg(?:\.tmp|\.json)?", candidate.name)
        if not match or candidate.resolve().parent != root or candidate.stat().st_mtime >= older_than:
            continue
        if candidate.suffix == ".ogg" and match[1] in known:
            continue
        candidate.unlink(missing_ok=True)
        removed += 1
    return removed
