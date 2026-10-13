import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.db.models import Base
from app.db.session import make_engine
from app.gateway import protocol

# Каждое событие WebSocket, которое сервер отправляет в тестах, сверяется с контрактом (app/gateway/protocol.py)
protocol.STRICT = True


@pytest.fixture(autouse=True)
def _contract():
    protocol.VIOLATIONS.clear()
    yield
    assert not protocol.VIOLATIONS, "события не сходятся с app/gateway/protocol.py:\n" + "\n".join(protocol.VIOLATIONS)


# По умолчанию — SQLite в файле. В CI и локально можно проверить на PostgreSQL:
# TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/taleforge_test pytest
PG_URL = os.environ.get("TEST_DATABASE_URL")
WORKER = os.environ.get("PYTEST_XDIST_WORKER")  # gw0, gw1… при запуске с -n


@pytest.fixture(autouse=True)
def _postgres_test_loops(monkeypatch):
    """TestClient and asyncio.run use different loops; asyncpg connections cannot cross them.

    Disable connection reuse only in PostgreSQL tests. Production retains its
    normal pool; row locks and real two-session concurrency are still tested.
    """
    if not PG_URL:
        return
    from sqlalchemy.pool import NullPool

    from app.db import session as db_session

    create_engine = db_session.create_async_engine

    def test_engine(url, **options):
        if str(url).startswith("postgresql"):
            options.setdefault("poolclass", NullPool)
        return create_engine(url, **options)

    monkeypatch.setattr(db_session, "create_async_engine", test_engine)


async def _reset(url: str) -> None:
    engine = make_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def _create_database(url: str) -> None:
    """Своя база для каждого рабочего процесса pytest: тесты чистят схему целиком и мешали бы друг другу."""
    base, _, name = url.rpartition("/")
    engine = make_engine(f"{base}/postgres")
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            if not await conn.scalar(text("select 1 from pg_database where datname = :n"), {"n": name}):
                await conn.execute(text(f'create database "{name}"'))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def database_url(tmp_path_factory) -> str | None:
    """Адрес PostgreSQL для этого процесса: у каждого рабочего своя база. Без PostgreSQL — None (SQLite)."""
    if not PG_URL:
        return None
    url = f"{PG_URL}_{WORKER}" if WORKER else PG_URL
    asyncio.run(_create_database(url))
    return url


@pytest.fixture
def settings(tmp_path, database_url, _postgres_test_loops):
    url = database_url or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    asyncio.run(_reset(url))
    return Settings(
        database_url=url,
        jwt_secret="test-secret-test-secret-test-secret-0123",
        public_url="http://play.test",
        superadmin_name="root",
        superadmin_password="rootpass",
        voicestudio_api_base="",  # без локального Voice Studio: тесты не ходят в сеть за репликой
    )


@pytest.fixture
def client(settings):
    from app.main import create_app

    with TestClient(create_app(settings)) as c:
        # здесь настоящий LiteLLM-клиент: фоновый режиссёр не должен ходить в сеть и забирать задания,
        # которые тест ведёт сам. Подключение режиссёра проверяет tests/test_narrative_startup.py
        c.app.state.master.narrative_preparer = None
        c.app.state.master.signal_recovery = lambda: None
        yield c


def login(client, name, password):
    r = client.post("/api/auth/login", json={"name": name, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def root(client):
    return login(client, "root", "rootpass")


@pytest.fixture
def admin(client, root):
    r = client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
    assert r.status_code == 201, r.text
    return login(client, "Arty", "secret1")
