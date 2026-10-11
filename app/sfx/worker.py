"""Durable single-inference coordinator. SQLite locally; PostgreSQL in Compose."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import math
import os
import sys
import tempfile
import time

from sqlalchemy import func, select

from app.config import Settings
from app.db.models import SfxAsset, SfxJob, SfxSound, new_id
from app.sfx.contracts import parameters_key
from app.sfx.service import queue_lock
from app.sfx.storage import MAX_ASSET_BYTES, asset_path, sweep_orphans

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 2


class Worker:
    def __init__(self, maker, settings: Settings, *, renderer=None):
        self.maker, self.settings = maker, settings
        self.renderer = renderer or self.render
        self.task: asyncio.Task | None = None
        self.last_sweep = 0.0

    async def render(self, parameters: dict, seed: int, output) -> dict:
        result = output.with_suffix(".json")
        spec = {
            "parameters": parameters,
            "seed": seed,
            "output": str(output),
            "result": str(result),
            "model_dir": str(self.settings.sfx_model_dir),
            "threads": self.settings.sfx_threads,
            "timeout": self.settings.sfx_timeout_seconds,
        }
        env = {
            **os.environ,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "OMP_NUM_THREADS": str(self.settings.sfx_threads),
            "MKL_NUM_THREADS": str(self.settings.sfx_threads),
        }
        env.pop("HF_TOKEN", None)  # model downloads happen at startup, never during a game
        # Model progress must not accumulate in coordinator RAM or block on a full pipe.
        with tempfile.TemporaryFile() as errors:
            process = await asyncio.create_subprocess_exec(
                self.settings.sfx_python or sys.executable,
                "-m",
                "app.sfx.render",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=errors,
                env=env,
            )
            try:
                await asyncio.wait_for(
                    process.communicate(json.dumps(spec).encode()), timeout=self.settings.sfx_timeout_seconds
                )
                if process.returncode:
                    errors.seek(0, os.SEEK_END)
                    errors.seek(max(0, errors.tell() - 2000))
                    stderr = errors.read().decode(errors="replace")[-500:]
                    raise RuntimeError(stderr or f"SFX renderer exit {process.returncode}")
                return json.loads(result.read_text(encoding="utf-8"))
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()
                result.unlink(missing_ok=True)

    async def claim(self):
        async with self.maker() as session:
            lock = await queue_lock(session)
            now = time.time()
            if lock.lease_until > now:
                await session.rollback()
                return None
            stale = (
                await session.scalars(select(SfxJob).where(SfxJob.status == "running", SfxJob.lease_until <= now))
            ).all()
            for old in stale:
                old.status = "failed" if old.attempts >= MAX_ATTEMPTS else "queued"
                old.error = "worker перезапущен или истёк срок задачи"
                old.lease_token, old.lease_until = None, 0
            await session.flush()
            # Turn outbox jobs are invisible until commit and do not hold the global lock during LLM work.
            staged = (
                await session.scalars(select(SfxJob).where(SfxJob.status == "staged").order_by(SfxJob.created_at))
            ).all()
            for waiting in staged:
                sound = await session.get(SfxSound, waiting.sound_id)
                active = await session.scalar(
                    select(func.count()).select_from(SfxJob).where(SfxJob.status.in_(("queued", "running")))
                )
                campaign_active = await session.scalar(
                    select(func.count())
                    .select_from(SfxJob)
                    .join(SfxSound)
                    .where(SfxSound.campaign_id == sound.campaign_id, SfxJob.status.in_(("queued", "running")))
                )
                if active >= self.settings.sfx_max_queue or campaign_active >= self.settings.sfx_campaign_queue:
                    waiting.status, waiting.error = "failed", "очередь SFX заполнена после фиксации хода"
                else:
                    waiting.status = "queued"
                await session.flush()
            job = await session.scalar(
                select(SfxJob)
                .where(SfxJob.status == "queued", SfxJob.next_attempt_at <= now)
                .order_by(SfxJob.created_at)
                .limit(1)
            )
            if job is None:
                await session.commit()
                return None
            sound = await session.get(SfxSound, job.sound_id)
            token = new_id("sl")
            lock.lease_token, lock.lease_until = token, now + self.settings.sfx_timeout_seconds + 60
            job.status, job.lease_token, job.lease_until = "running", token, lock.lease_until
            job.attempts += 1
            await session.commit()
            return job.id, token, dict(job.parameters or sound.parameters), job.seed

    async def tick(self) -> bool:
        if not self.settings.sfx_enabled:
            return False
        claimed = await self.claim()
        if claimed is None:
            return False
        job_id, token, parameters, seed = claimed
        asset_id = new_id("sa")
        destination = asset_path(self.settings, asset_id)
        temporary = destination.with_suffix(".ogg.tmp")
        started = time.monotonic()
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            info = await asyncio.wait_for(self.renderer(parameters, seed, temporary), self.settings.sfx_timeout_seconds)
            data = await asyncio.to_thread(temporary.read_bytes)
            if not data.startswith(b"OggS") or not 32 <= len(data) <= MAX_ASSET_BYTES:
                raise ValueError("неверный результат генератора")
            duration = float(info["duration_seconds"])
            if not math.isfinite(duration) or abs(duration - parameters["duration_seconds"]) > 0.05:
                raise ValueError("неверная длительность результата")
            async with self.maker() as session:
                lock = await queue_lock(session)
                job = await session.get(SfxJob, job_id)
                if job is None or job.lease_token != token or lock.lease_token != token:
                    return True  # replaced/deleted lease: never publish this output
                used = await session.scalar(select(func.coalesce(func.sum(SfxAsset.size_bytes), 0)))
                if used + len(data) > self.settings.sfx_cache_max_bytes:
                    raise ValueError("квота хранилища SFX исчерпана")
                await asyncio.to_thread(os.replace, temporary, destination)
                session.add(
                    SfxAsset(
                        id=asset_id,
                        sound_id=job.sound_id,
                        duration_seconds=duration,
                        size_bytes=len(data),
                        digest=hashlib.sha256(data).hexdigest(),
                        seed=seed,
                        parameters=parameters,
                        cache_key=parameters_key(parameters),
                    )
                )
                sound = await session.get(SfxSound, job.sound_id)
                sound.current_asset_id = asset_id
                job.status, job.asset_id, job.error = "ready", asset_id, None
                job.elapsed_seconds = time.monotonic() - started
                job.lease_token, job.lease_until = None, 0
                lock.lease_token, lock.lease_until = None, 0
                await session.commit()
        except asyncio.CancelledError:
            raise  # render finally kills the process; expired lease is recovered after restart
        except Exception as exc:
            log.warning("SFX job %s failed: %s", job_id, exc)
            async with self.maker() as session:
                lock = await queue_lock(session)
                job = await session.get(SfxJob, job_id)
                if job and job.lease_token == token and lock.lease_token == token:
                    job.error = (str(exc) or type(exc).__name__)[:500]
                    job.status = "queued" if job.attempts < MAX_ATTEMPTS else "failed"
                    job.next_attempt_at = time.time() + 5
                    job.elapsed_seconds = time.monotonic() - started
                    job.lease_token, job.lease_until = None, 0
                    lock.lease_token, lock.lease_until = None, 0
                    await session.commit()
        finally:
            temporary.unlink(missing_ok=True)
            # A cancelled/failed commit can already be durable. Leave renamed files for the DB-aware
            # orphan sweep instead of deleting a file that a committed asset may now reference.
        return True

    async def run(self):
        while True:
            try:
                if time.time() - self.last_sweep > 600:
                    async with self.maker() as session:
                        known = set((await session.scalars(select(SfxAsset.id))).all())
                    await asyncio.to_thread(
                        sweep_orphans, self.settings, known, time.time() - self.settings.sfx_timeout_seconds - 120
                    )
                    self.last_sweep = time.time()
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("SFX coordinator unavailable; game continues")
            await asyncio.sleep(0.5)

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
