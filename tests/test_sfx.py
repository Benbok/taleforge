"""Generated SFX: durable cache, isolated inference and campaign authorization."""

import dataclasses
import hashlib
import json
from types import SimpleNamespace

import pytest

from app.core import audio
from tests.game import import_base, party, run


def sfx_settings(settings, tmp_path, **options):
    folder = tmp_path / "models"
    folder.mkdir(exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps({"revision": "main", "resolved_revision": "test-weights"}))
    return dataclasses.replace(
        settings, sfx_enabled=True, audio_dir=tmp_path / "audio", sfx_model_dir=folder, **options
    )


def test_sfx_only_campaign_enabled(tmp_path):
    audio.configure(tmp_path)
    assert audio.enabled(SimpleNamespace(settings={"audio_enabled": True}, pack_id=None, content_chain=[]))


def test_sfx_key_normalization_and_model_parameters():
    from app.config import Settings
    from app.sfx.contracts import SfxInput, cache_key

    settings = Settings()
    a = SfxInput(description="  Door   CREAKING loudly  ", duration_seconds=2)
    b = SfxInput(description="door creaking loudly", duration_seconds=2)
    assert cache_key(a, settings) == cache_key(b, settings)
    assert cache_key(SfxInput(description=a.description), settings) == cache_key(
        SfxInput(description=a.description, duration_seconds=3.0), settings
    )
    assert cache_key(a, settings) != cache_key(a, dataclasses.replace(settings, sfx_steps=9))
    assert cache_key(a, settings) != cache_key(a, dataclasses.replace(settings, sfx_model_revision="different"))
    for raw in ({"description": "short"}, {"description": "Door creaking loudly", "duration_seconds": 5}):
        with pytest.raises(ValueError):
            SfxInput.model_validate(raw)


def test_prepare_localizes_encoder_and_restarts_offline(settings, tmp_path, monkeypatch):
    import sys
    from types import ModuleType

    from app.sfx.prepare import REPO, prepare

    cfg = sfx_settings(settings, tmp_path)
    (cfg.sfx_model_dir / "manifest.json").write_text("corrupted")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    encoder = snapshot / "t5gemma-b-b-ul2"
    encoder.mkdir()
    (encoder / "model.safetensors").write_bytes(b"encoder weights")
    (snapshot / "model.safetensors").write_bytes(b"audio weights")
    (snapshot / "model_config.json").write_text(
        json.dumps(
            {
                "conditioning": [
                    {
                        "type": "t5gemma",
                        "config": {
                            "repo_id": REPO,
                            "subfolder": "t5gemma-b-b-ul2",
                            "model_name": "google/t5gemma-b-b-ul2",
                        },
                    }
                ],
            }
        )
    )
    calls = []
    hub = ModuleType("huggingface_hub")

    class Api:
        def __init__(self, token):
            pass

        def model_info(self, repo, revision):
            calls.append((repo, revision))
            return SimpleNamespace(sha="immutable-sha")

    def download(repo, revision=None, token=None):
        calls.append((repo, revision))
        return str(snapshot)

    hub.HfApi, hub.snapshot_download = Api, download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    prepare(cfg)
    assert calls == [(REPO, "main"), (REPO, "immutable-sha")]
    localized = json.loads((cfg.sfx_model_dir / "model_config.json").read_text())["conditioning"][0]["config"]
    assert localized["model_path"] == str(snapshot) and localized["subfolder"] == encoder.name
    assert (cfg.sfx_model_dir / "model.safetensors").read_bytes() == b"audio weights"
    assert json.loads((cfg.sfx_model_dir / "manifest.json").read_text())["resolved_revision"] == "immutable-sha"
    calls.clear()
    prepare(cfg)
    assert calls == []  # prepared startup doesn't need a network connection


def test_durable_dedup_queue_and_disabled(settings, client, admin, tmp_path):
    from app.sfx.contracts import SfxInput
    from app.sfx.service import enqueue

    import_base(settings)
    campaign, _, _ = party(client, admin)
    cfg = sfx_settings(settings, tmp_path, sfx_max_queue=1)

    async def go(session):
        a = SfxInput(description="A heavy wooden door creaks", duration_seconds=2)
        first = await enqueue(session, cfg, campaign["id"], a)
        second = await enqueue(session, cfg, campaign["id"], a)
        assert first["job_id"] == second["job_id"]
        assert first["sound_id"] == second["sound_id"]
        full = await enqueue(session, cfg, campaign["id"], SfxInput(description="A distant thunder explosion"))
        assert full["status"] == "skipped"
        off = await enqueue(session, dataclasses.replace(cfg, sfx_enabled=False), campaign["id"], a)
        assert off["status"] == "skipped"
        await session.commit()
        return first

    assert run(settings, go)["status"] == "queued"


def test_worker_cache_regeneration_and_failure_preserve_version(settings, client, admin, tmp_path):
    from app.db.models import SfxSound
    from app.db.session import make_engine, make_sessionmaker
    from app.sfx.contracts import SfxInput
    from app.sfx.service import enqueue
    from app.sfx.worker import Worker

    import_base(settings)
    campaign, _, _ = party(client, admin)
    cfg = sfx_settings(settings, tmp_path)
    calls = []

    async def render(params, seed, output):
        calls.append(seed)
        data = b"OggS" + bytes([len(calls)]) * 100
        output.write_bytes(data)
        return {"duration_seconds": 3.0, "size_bytes": len(data), "digest": hashlib.sha256(data).hexdigest()}

    async def go(session):
        engine = make_engine(cfg.database_url)
        maker = make_sessionmaker(engine)
        worker = Worker(maker, cfg, renderer=render)
        a = SfxInput(description="Thunder cracking above the stone tower")
        first = await enqueue(session, cfg, campaign["id"], a)
        await session.commit()
        assert await worker.tick()
        cached = await enqueue(session, cfg, campaign["id"], a)
        assert cached["status"] == "cached" and len(calls) == 1
        original = cached["asset_id"]
        await enqueue(session, cfg, campaign["id"], a, regenerate_id=first["sound_id"])
        await session.commit()
        assert await worker.tick()
        session.expire_all()
        sound = await session.get(SfxSound, first["sound_id"])
        assert sound.current_asset_id != original and len(calls) == 2
        current = sound.current_asset_id
        await enqueue(session, cfg, campaign["id"], a, regenerate_id=first["sound_id"])
        await session.commit()

        async def broken(*args):
            raise RuntimeError("model unavailable")

        worker.renderer = broken
        assert await worker.tick()
        session.expire_all()
        assert (await session.get(SfxSound, first["sound_id"])).current_asset_id == current
        assert (cfg.audio_dir / "generated" / f"{original}.ogg").is_file()
        await engine.dispose()

    run(settings, go)


def test_concurrent_staged_and_manual_cache_misses(settings, client, admin, tmp_path):
    import asyncio

    from sqlalchemy import func, select

    from app.db.models import SfxJob, SfxSound
    from app.db.session import make_engine, make_sessionmaker
    from app.sfx.contracts import SfxInput
    from app.sfx.service import enqueue

    import_base(settings)
    campaign, _, _ = party(client, admin)
    cfg = sfx_settings(settings, tmp_path)

    async def go(session):
        engine = make_engine(cfg.database_url)
        maker = make_sessionmaker(engine)

        async def request(staged):
            async with maker() as other:
                result = await enqueue(
                    other, cfg, campaign["id"], SfxInput(description="A heavy oak door creaks"), staged=staged
                )
                await other.commit()
                return result

        first, second = await asyncio.gather(request(True), request(False))
        assert first["sound_id"] == second["sound_id"] and first["job_id"] == second["job_id"]
        assert await session.scalar(select(func.count()).select_from(SfxSound)) == 1
        assert await session.scalar(select(func.count()).select_from(SfxJob)) == 1
        await engine.dispose()

    run(settings, go)


@pytest.mark.parametrize("completed", ["failed", "deleted", "ready"])
def test_competing_job_finishes_during_staged_admission(settings, client, admin, tmp_path, monkeypatch, completed):
    from sqlalchemy import delete, update
    from sqlalchemy.sql.dml import Insert

    from app.db.models import SfxAsset, SfxJob, new_id
    from app.sfx.contracts import SfxInput
    from app.sfx.service import enqueue, insert_for
    from app.sfx.storage import asset_path

    import_base(settings)
    campaign, _, _ = party(client, admin)
    cfg = sfx_settings(settings, tmp_path)

    async def go(session):
        original = session.scalar

        async def racing_scalar(statement, *args, **kwargs):
            if isinstance(statement, Insert) and statement.table.name == "sfx_jobs":
                values = statement.compile().params
                winner = new_id("sj")
                await original(
                    insert_for(session)(SfxJob)
                    .values(
                        id=winner,
                        sound_id=values["sound_id"],
                        parameters=values["parameters"],
                        status="queued",
                    )
                    .returning(SfxJob.id)
                )
                result = await original(statement, *args, **kwargs)
                assert result is None  # competing active job wins the unique-index conflict
                if completed == "deleted":
                    await session.execute(delete(SfxJob).where(SfxJob.id == winner))
                elif completed == "ready":
                    asset = SfxAsset(
                        sound_id=values["sound_id"], duration_seconds=3, size_bytes=104, digest="abc", seed=0
                    )
                    session.add(asset)
                    await session.flush()
                    path = asset_path(cfg, asset.id)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"OggS" + b"a" * 100)
                    await session.execute(
                        update(SfxJob).where(SfxJob.id == winner).values(status="ready", asset_id=asset.id)
                    )
                else:
                    await session.execute(update(SfxJob).where(SfxJob.id == winner).values(status="failed"))
                return result
            return await original(statement, *args, **kwargs)

        monkeypatch.setattr(session, "scalar", racing_scalar)
        result = await enqueue(
            session, cfg, campaign["id"], SfxInput(description="A massive oak door creaks"), staged=True
        )
        assert result["status"] == ("cached" if completed == "ready" else "skipped")
        await session.commit()

    run(settings, go)


def test_regeneration_snapshots_new_model_and_reuses_updated_cache(settings, client, admin, tmp_path):
    from app.db.session import make_engine, make_sessionmaker
    from app.sfx.contracts import SfxInput
    from app.sfx.service import enqueue
    from app.sfx.worker import Worker

    import_base(settings)
    campaign, _, _ = party(client, admin)
    cfg = sfx_settings(settings, tmp_path)
    calls = []

    async def render(params, seed, output):
        calls.append(params["weights_digest"])
        output.write_bytes(b"OggS" + b"a" * 100)
        return {"duration_seconds": 3}

    async def go(session):
        engine = make_engine(cfg.database_url)
        worker = Worker(make_sessionmaker(engine), cfg, renderer=render)
        request = SfxInput(description="An iron gate closes with a loud clang")
        first = await enqueue(session, cfg, campaign["id"], request)
        await session.commit()
        await worker.tick()
        (cfg.sfx_model_dir / "manifest.json").write_text(
            json.dumps({"revision": "main", "resolved_revision": "updated-weights"})
        )
        await enqueue(session, cfg, campaign["id"], request, regenerate_id=first["sound_id"])
        await session.commit()
        await worker.tick()
        session.expire_all()
        cached = await enqueue(session, cfg, campaign["id"], request)
        assert calls == ["test-weights", "updated-weights"]
        assert cached["status"] == "cached" and cached["sound_id"] == first["sound_id"]
        await engine.dispose()

    run(settings, go)


@pytest.mark.parametrize("failure", ["quota", "timeout"])
def test_worker_failure_limits_and_cleans_unpublished_files(settings, client, admin, tmp_path, failure):
    import asyncio

    from app.db.models import SfxJob, SfxSound
    from app.db.session import make_engine, make_sessionmaker
    from app.sfx.contracts import SfxInput
    from app.sfx.service import enqueue
    from app.sfx.worker import Worker

    import_base(settings)
    campaign, _, _ = party(client, admin)
    cfg = sfx_settings(
        settings, tmp_path, sfx_cache_max_bytes=32, sfx_timeout_seconds=0.02 if failure == "timeout" else 1
    )
    cancelled = []

    async def render(params, seed, output):
        output.write_bytes(b"OggS" + b"a" * 100)
        if failure == "timeout":
            try:
                await asyncio.sleep(1)
            finally:
                cancelled.append(True)
        return {"duration_seconds": 3}

    async def go(session):
        engine = make_engine(cfg.database_url)
        worker = Worker(make_sessionmaker(engine), cfg, renderer=render)
        result = await enqueue(session, cfg, campaign["id"], SfxInput(description="A short and loud clap of thunder"))
        await session.commit()
        for attempt in (1, 2):
            assert await worker.tick()
            session.expire_all()
            job = await session.get(SfxJob, result["job_id"])
            assert job.attempts == attempt and job.status == ("queued" if attempt == 1 else "failed")
            job.next_attempt_at = 0
            await session.commit()
        assert (await session.get(SfxSound, result["sound_id"])).current_asset_id is None
        assert not list((cfg.audio_dir / "generated").glob("*"))
        assert len(cancelled) == (2 if failure == "timeout" else 0)
        await engine.dispose()

    run(settings, go)


def test_sfx_migration_upgrade_and_downgrade(monkeypatch, tmp_path):
    import sqlite3
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    db_path = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    command.upgrade(config, "0018")
    command.upgrade(config, "0019")
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT lease_until FROM sfx_lock WHERE id=1").fetchone() == (0,)
        indexes = {row[1] for row in db.execute("PRAGMA index_list(sfx_jobs)")}
        assert "uq_sfx_jobs_active_sound" in indexes
    command.downgrade(config, "0018")
    with sqlite3.connect(db_path) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'sfx_%'").fetchall()
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0018",)


def test_single_worker_lease_and_bounded_recovery(settings, client, admin, tmp_path):
    import time

    from sqlalchemy import select

    from app.db.models import SfxJob, SfxLock
    from app.db.session import make_engine, make_sessionmaker
    from app.sfx.contracts import SfxInput
    from app.sfx.service import enqueue
    from app.sfx.worker import Worker

    import_base(settings)
    campaign, _, _ = party(client, admin)
    cfg = sfx_settings(settings, tmp_path)

    async def go(session):
        engine = make_engine(cfg.database_url)
        maker = make_sessionmaker(engine)
        first, second = Worker(maker, cfg), Worker(maker, cfg)
        receipt = await enqueue(session, cfg, campaign["id"], SfxInput(description="A long iron chain rattles"))
        await session.commit()
        assert await first.claim()
        assert await second.claim() is None
        for attempt in (1, 2):
            async with maker() as other:
                lock = await other.get(SfxLock, 1)
                job = await other.get(SfxJob, receipt["job_id"])
                assert job.attempts == attempt
                lock.lease_until = job.lease_until = time.time() - 1
                await other.commit()
            claimed = await second.claim()
            assert bool(claimed) == (attempt == 1)
        async with maker() as other:
            job = await other.scalar(select(SfxJob).where(SfxJob.id == receipt["job_id"]))
            assert job.status == "failed" and job.attempts == 2
        await engine.dispose()

    run(settings, go)


def test_worker_cancellation_after_commit_retains_published_file(settings, client, admin, tmp_path):
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db.models import SfxJob, SfxSound
    from app.db.session import make_engine, make_sessionmaker
    from app.sfx.contracts import SfxInput
    from app.sfx.service import enqueue
    from app.sfx.storage import asset_path
    from app.sfx.worker import Worker

    import_base(settings)
    campaign, _, _ = party(client, admin)
    cfg = sfx_settings(settings, tmp_path)

    class InterruptedSession(AsyncSession):
        async def commit(self):
            publication = any(isinstance(row, SfxJob) and row.status == "ready" for row in self.identity_map.values())
            await super().commit()
            if publication:
                raise asyncio.CancelledError

    async def render(params, seed, output):
        output.write_bytes(b"OggS" + b"a" * 100)
        return {"duration_seconds": 3}

    async def go(session):
        receipt = await enqueue(session, cfg, campaign["id"], SfxInput(description="Iron chains clank in a stone room"))
        await session.commit()
        engine = make_engine(cfg.database_url)
        worker = Worker(make_sessionmaker(engine, class_=InterruptedSession), cfg, renderer=render)
        with pytest.raises(asyncio.CancelledError):
            await worker.tick()
        session.expire_all()
        sound = await session.get(SfxSound, receipt["sound_id"])
        assert sound.current_asset_id and asset_path(cfg, sound.current_asset_id).is_file()
        assert (await session.get(SfxJob, receipt["job_id"])).status == "ready"
        await engine.dispose()

    run(settings, go)


def test_wav_validation_rejects_silence_and_wrong_duration(tmp_path):
    import array
    import math
    import shutil
    import wave

    from app.sfx.storage import encode_wav, validate_wav

    path = tmp_path / "sound.wav"

    def wav(seconds, amplitude):
        samples = array.array("h", (int(amplitude * math.sin(i / 20)) for i in range(round(seconds * 24000))))
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(24000)
            out.writeframes(samples.tobytes())

    wav(3, 0)
    with pytest.raises(ValueError, match="тишину"):
        validate_wav(path, 3)
    wav(5, 10000)
    with pytest.raises(ValueError, match="длительность"):
        validate_wav(path, 3)
    wav(3, 20000)
    assert validate_wav(path, 3) == 3
    if shutil.which("ffmpeg"):
        output = tmp_path / "sound.ogg.tmp"
        meta = encode_wav(path, output, 3)
        assert output.read_bytes().startswith(b"OggS") and meta["duration_seconds"] == 3


def test_generated_tool_reserves_budget_and_rolls_back(settings, client, admin, tmp_path):
    from sqlalchemy import func, select

    from app.db.models import Campaign, SfxJob, SfxPlayback
    from app.tools.registry import execute
    from app.tools.runtime import open_context
    from tests.game import QueueDice, ok

    import_base(settings)
    campaign, _, _ = party(client, admin)
    ok(
        client.patch(
            f"/api/campaigns/{campaign['id']}", json={"audio_enabled": True, "sfx_enabled": True}, headers=admin
        )
    )
    cfg = sfx_settings(settings, tmp_path)

    async def go(session):
        session.info["settings"] = cfg
        ctx = await open_context(
            session, await session.get(Campaign, campaign["id"]), QueueDice([]), turn_id="t_generated", seat_id=None
        )
        out = await execute(ctx, "request_sfx", {"description": "Heavy stone door slowly opens"})
        assert out["ok"] and out["result"]["status"] == "queued"
        assert len(ctx.sfx_requests) == 1
        again = await execute(ctx, "request_sfx", {"description": "Another massive door opens"})
        assert again["ok"] and again["result"]["status"] == "skipped"
        assert await session.scalar(select(func.count()).select_from(SfxPlayback)) == 1
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(SfxJob)) == 0

    run(settings, go)


def test_generation_disabled_allows_only_existing_saved_files(settings, client, admin, tmp_path):
    from sqlalchemy import func, select

    from app.db.models import Campaign, SfxAsset, SfxJob, SfxSound
    from app.sfx.contracts import SfxInput, cache_key, parameters
    from app.sfx.storage import asset_path
    from app.tools.registry import execute
    from app.tools.runtime import open_context
    from tests.game import QueueDice, ok

    import_base(settings)
    campaign, _, _ = party(client, admin)
    ok(
        client.patch(
            f"/api/campaigns/{campaign['id']}", json={"audio_enabled": True, "sfx_enabled": False}, headers=admin
        )
    )
    cfg = sfx_settings(settings, tmp_path)

    async def go(session):
        session.info["settings"] = cfg
        request = SfxInput(description="A wooden door creaks open slowly")
        sound = SfxSound(
            campaign_id=campaign["id"],
            cache_key=cache_key(request, cfg),
            title="Дверь",
            description=request.description,
            parameters=parameters(request, cfg),
        )
        session.add(sound)
        await session.flush()
        asset = SfxAsset(sound_id=sound.id, duration_seconds=3, size_bytes=104, digest="abc", seed=0)
        session.add(asset)
        await session.flush()
        sound.current_asset_id = asset.id
        await session.commit()
        c = await session.get(Campaign, campaign["id"])
        ctx = await open_context(session, c, QueueDice([]), turn_id="t_disabled_missing", seat_id=None)
        missing = await execute(ctx, "request_sfx", {"sound_id": sound.id})
        assert missing["ok"] and missing["result"]["status"] == "skipped"
        assert await session.scalar(select(func.count()).select_from(SfxJob)) == 0
        path = asset_path(cfg, asset.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"OggS" + b"a" * 100)
        ctx = await open_context(session, c, QueueDice([]), turn_id="t_disabled_cached", seat_id=None)
        ready = await execute(ctx, "request_sfx", {"sound_id": sound.id})
        assert ready["ok"] and ready["result"]["status"] == "cached"
        assert await session.scalar(select(func.count()).select_from(SfxJob)) == 0

    run(settings, go)


def test_saved_audio_api_authorization_and_management(settings, client, admin, tmp_path):
    from app.db.models import SfxAsset, SfxSound
    from app.sfx.contracts import SfxInput, cache_key, parameters
    from app.sfx.storage import asset_path
    from tests.test_api import invite, make_campaign, register

    import_base(settings)
    campaign, (player,), _ = party(client, admin)
    other = make_campaign(client, admin)
    outsider = register(client, invite(client, admin, other["id"])["token"], "Чужой")
    cfg = sfx_settings(settings, tmp_path)
    client.app.state.settings = cfg

    async def save(session):
        a = SfxInput(description="Wooden door slowly creaks open")
        sound = SfxSound(
            campaign_id=campaign["id"],
            cache_key=cache_key(a, cfg),
            title="Скрип двери",
            description=a.description,
            parameters=parameters(a, cfg),
        )
        session.add(sound)
        await session.flush()
        asset = SfxAsset(sound_id=sound.id, duration_seconds=3, size_bytes=104, seed=0, digest="abc")
        session.add(asset)
        await session.flush()
        sound.current_asset_id = asset.id
        path = asset_path(cfg, asset.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"OggS" + b"a" * 100)
        await session.commit()
        return sound.id, asset.id

    sid, aid = run(settings, save)
    base = f"/api/campaigns/{campaign['id']}/sfx"
    assert client.get(base).status_code == 401
    assert client.get(base, headers=outsider).status_code == 404
    data = client.get(base, headers=player).json()
    assert data["sounds"][0]["title"] == "Скрип двери"
    url = data["sounds"][0]["versions"][0]["url"]
    response = client.get(url, headers=player)
    assert response.content.startswith(b"OggS") and response.headers["vary"] == "Authorization"
    assert client.get(url, headers=outsider).status_code == 404
    assert client.get(f"/api/campaigns/{other['id']}/sfx/assets/{aid}", headers=outsider).status_code == 404
    assert client.patch(f"{base}/{sid}", json={"title": "Новое имя"}, headers=player).status_code == 403
    assert client.post(f"{base}/{sid}/regenerate", headers=player).status_code == 403
    assert client.delete(f"{base}/{sid}", headers=player).status_code == 403
    assert client.patch(f"{base}/{sid}", json={"title": "Дверь", "pinned": True}, headers=admin).status_code == 200
    assert client.post(f"{base}/{sid}/regenerate", headers=admin).json()["status"] == "queued"
    assert client.get(url, headers=player).status_code == 200  # old file remains during regeneration
    assert client.delete(f"{base}/{sid}", headers=admin).status_code == 409


@pytest.mark.parametrize("elsewhere_combat", [False, True])
def test_delivery_after_text_and_stale_group_dedup(settings, client, admin, tmp_path, elsewhere_combat):
    import time

    from sqlalchemy import select, update

    from app.db.models import Campaign, SfxAsset, SfxPlayback, SfxSound
    from app.db.session import make_engine, make_sessionmaker
    from app.sfx.contracts import SfxInput, cache_key, parameters
    from app.sfx.playback import Delivery
    from app.sfx.storage import asset_path
    from app.tools.registry import execute
    from app.tools.runtime import flush_outbox, open_context, publish_changes
    from tests.game import QueueDice, ok
    from tests.test_party_split import _split_party

    cid, _, (hero1, hero2), places = _split_party(client, admin, settings)
    ok(client.patch(f"/api/campaigns/{cid}", json={"audio_enabled": True, "sfx_enabled": True}, headers=admin))
    cfg = sfx_settings(settings, tmp_path)

    class Bus:
        def __init__(self):
            self.events = []

        async def publish(self, cid, event, seats):
            self.events.append((event, seats))

    async def go(session):
        bus = Bus()
        engine = make_engine(cfg.database_url)
        maker = make_sessionmaker(engine)
        delivery = Delivery(maker, cfg, bus)
        a = SfxInput(description="Wood creaking in the gloomy docks")
        sound = SfxSound(
            campaign_id=cid,
            cache_key=cache_key(a, cfg),
            title="Доковый скрип",
            description=a.description,
            parameters=parameters(a, cfg),
        )
        session.add(sound)
        await session.flush()
        asset = SfxAsset(sound_id=sound.id, duration_seconds=3, size_bytes=100, seed=0, digest="abc")
        session.add(asset)
        await session.flush()
        sound.current_asset_id = asset.id
        path = asset_path(cfg, asset.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"OggS" + b"x" * 96)
        await session.commit()
        session.info["settings"] = cfg
        c = await session.get(Campaign, cid)
        ctx = await open_context(
            session, c, QueueDice([]), turn_id="t_sfx_delivery", seat_id=None, focus=places["docks"]
        )
        if elsewhere_combat:
            ctx.world.scene.mode, ctx.world.scene.round = "combat", 2
            ctx.world.scene.turn_order = [{"id": hero1["id"], "initiative": 15}]
        result = await execute(ctx, "request_sfx", {"sound_id": sound.id})
        assert result["ok"] and result["result"]["status"] == "cached"
        messages = await flush_outbox(session, ctx)
        await session.commit()
        assert await delivery.tick() == 0  # no sound before narration publication
        await publish_changes(bus, ctx, messages)
        assert await delivery.tick() == 1
        assert await delivery.tick() == 0
        ready = [(event, seats) for event, seats in bus.events if event["type"] == "audio.sfx_ready"]
        assert len(ready) == (2 if elsewhere_combat else 1)
        player_event = next(event for event, seats in ready if hero2["seat_id"] in seats)
        assert player_event["payload"]["mode"] == "free" and player_event["payload"]["round"] == 0
        assert all(hero1["seat_id"] not in seats for _, seats in ready)
        # Expiry and a different group context suppress later deliveries.
        row = await session.scalar(select(SfxPlayback).where(SfxPlayback.turn_id == "t_sfx_delivery"))
        await session.execute(
            update(SfxPlayback).where(SfxPlayback.id == row.id).values(status="armed", expires_at=time.time() - 1)
        )
        await session.commit()
        assert await delivery.tick() == 0
        await session.refresh(row)
        assert row.status == "skipped"
        context = dict(row.context)
        context["game_time"] += 1
        await session.execute(
            update(SfxPlayback)
            .where(SfxPlayback.id == row.id)
            .values(status="armed", expires_at=time.time() + 10, context=context)
        )
        await session.commit()
        assert await delivery.tick() == 0
        await session.refresh(row)
        assert row.status == "skipped"
        await engine.dispose()

    run(settings, go)
