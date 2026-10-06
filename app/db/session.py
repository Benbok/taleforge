from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_READS = {"SELECT", "PRAGMA", "EXPLAIN"}


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

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def _begin_on_write(conn, cursor, statement, *_):
            # Транзакция открывается перед первой записью и сразу берёт право записи (BEGIN IMMEDIATE), а чтения
            # до неё идут без транзакции, как в READ COMMITTED у PostgreSQL. Обычный BEGIN падал с «database is
            # locked», когда сессия сначала читала, а потом писала, пока пишет другая (фоновый ход мастера и
            # запрос REST): SQLite не ждёт в этом случае. BEGIN IMMEDIATE с самого начала ждёт чужую запись, но
            # держал бы запись всю сессию, даже только читающую, и запросы с вложенной сессией застревали бы.
            in_tx = conn.connection.dbapi_connection._connection.in_transaction
            if in_tx or statement.split(None, 1)[0].upper() in _READS:
                return
            cursor.execute("BEGIN IMMEDIATE")

    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with maker() as session:
        yield session
