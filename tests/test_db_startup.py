import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import DBAPIError

from app.db import session


def db_error(sqlstate):
    original = Exception("database connection failed")
    original.sqlstate = sqlstate
    return DBAPIError(None, None, original)


@pytest.mark.parametrize("error", [db_error("57P03"), ConnectionRefusedError()])
def test_startup_waits_for_database_recovery(monkeypatch, error):
    connection = SimpleNamespace(close=AsyncMock())
    engine = SimpleNamespace(connect=AsyncMock(side_effect=[error, error, connection]))
    sleep = AsyncMock()
    monkeypatch.setattr(session.asyncio, "sleep", sleep)

    async def run():
        async with session.startup_connection(engine) as actual:
            assert actual is connection

    asyncio.run(run())
    assert engine.connect.await_count == 3
    assert sleep.await_count == 2
    connection.close.assert_awaited_once()


def test_startup_does_not_retry_invalid_credentials(monkeypatch):
    error = db_error("28P01")
    engine = SimpleNamespace(connect=AsyncMock(side_effect=error))
    sleep = AsyncMock()
    monkeypatch.setattr(session.asyncio, "sleep", sleep)

    async def run():
        async with session.startup_connection(engine):
            pytest.fail("connection should fail")

    with pytest.raises(DBAPIError) as caught:
        asyncio.run(run())
    assert caught.value is error
    engine.connect.assert_awaited_once()
    sleep.assert_not_awaited()


def test_startup_retry_is_bounded(monkeypatch):
    error = db_error("57P03")
    engine = SimpleNamespace(connect=AsyncMock(side_effect=error))
    sleep = AsyncMock()
    monkeypatch.setattr(session.asyncio, "sleep", sleep)

    async def run():
        async with session.startup_connection(engine, attempts=3):
            pytest.fail("connection should fail")

    with pytest.raises(DBAPIError):
        asyncio.run(run())
    assert engine.connect.await_count == 3
    assert sleep.await_count == 2


def test_migration_errors_are_not_retried():
    connection = SimpleNamespace(close=AsyncMock())
    engine = SimpleNamespace(connect=AsyncMock(return_value=connection))
    migration = Mock(side_effect=db_error("57P03"))

    async def run():
        async with session.startup_connection(engine):
            migration()

    with pytest.raises(DBAPIError):
        asyncio.run(run())
    engine.connect.assert_awaited_once()
    migration.assert_called_once()
    connection.close.assert_awaited_once()
