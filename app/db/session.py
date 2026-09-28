from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def make_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(url, pool_pre_ping=not url.startswith("sqlite"))
    if url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _fk_on(dbapi_conn, _):  # SQLite по умолчанию не проверяет внешние ключи
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
            # Драйвер sqlite сам решает, когда открыть транзакцию, и ломает точки сохранения (SAVEPOINT):
            # отключаем его логику и открываем транзакцию явно — так откат хода мастера откатывает и инструменты
            dbapi_conn.isolation_level = None

        @event.listens_for(engine.sync_engine, "begin")
        def _begin(conn):
            conn.exec_driver_sql("BEGIN")

    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with maker() as session:
        yield session
