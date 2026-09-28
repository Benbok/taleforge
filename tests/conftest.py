import asyncio
import os

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db.models import Base
from app.db.session import make_engine

# По умолчанию — SQLite в файле. В CI и локально можно проверить на PostgreSQL:
# TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/taleforge_test pytest
PG_URL = os.environ.get("TEST_DATABASE_URL")


async def _reset(url: str) -> None:
    engine = make_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture
def settings(tmp_path):
    url = PG_URL or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    asyncio.run(_reset(url))
    return Settings(
        database_url=url,
        jwt_secret="test-secret-test-secret-test-secret-0123",
        public_url="http://play.test",
        superadmin_name="root",
        superadmin_password="rootpass",
    )


@pytest.fixture
def client(settings):
    from app.main import create_app

    with TestClient(create_app(settings)) as c:
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
