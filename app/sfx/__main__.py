"""Compose worker: prepare persistent weights automatically, then consume the SQL queue."""

import asyncio
import logging
import os

from app.config import Settings
from app.db.session import make_engine, make_sessionmaker
from app.sfx.prepare import prepare
from app.sfx.worker import Worker

log = logging.getLogger(__name__)


async def main():
    cfg = Settings.from_env()
    # A missing token/license never prevents the application container from starting.
    while cfg.sfx_enabled:
        try:
            await asyncio.to_thread(prepare, cfg)
            break
        except Exception as exc:
            token = os.environ.get("HF_TOKEN", "")
            message = str(exc).replace(token, "[redacted]") if token else str(exc)
            log.error("SFX startup: %s; retry in 60s. Check HF_TOKEN and model access.", message[:700])
            await asyncio.sleep(60)
    engine = make_engine(cfg.database_url)
    worker = Worker(make_sessionmaker(engine), cfg)
    try:
        await worker.run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
