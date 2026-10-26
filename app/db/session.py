from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_READS = {"SELECT", "PRAGMA", "EXPLAIN"}


async def verify_universal_schema(engine: AsyncEngine) -> None:
    """Reject legacy storage before bootstrap writes; initialize only an empty database."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    def verify(connection):
        tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
        if not tables:
            config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            return
        if not {"hero_dialogues", "hero_edit_receipts", "library_characters"} <= tables:
            raise RuntimeError(
                "Expected a universal database; configure a NEW DATABASE_URL and run alembic upgrade head"
            )
        columns = {c["name"] for c in inspect(connection).get_columns("library_characters")}
        if "revision" not in columns:
            raise RuntimeError("Expected universal hero revisions; run alembic upgrade head")
        if "hero_portraits" not in tables or not {"portrait_id", "portrait_job_id"} <= columns:
            raise RuntimeError("Expected hero portrait storage; run alembic upgrade head")
        if not {"runtime_profiles", "hero_abilities"} <= tables:
            raise RuntimeError("Expected universal action storage; run alembic upgrade head")
        if not {"universal_clocks", "universal_steps", "universal_effects", "universal_exchanges"} <= tables:
            raise RuntimeError("Expected universal exploration storage; run alembic upgrade head")
        if "universal_journal" not in tables:
            raise RuntimeError("Expected the universal journal; run alembic upgrade head")

    async with engine.begin() as connection:
        await connection.run_sync(verify)


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


def make_sessionmaker(engine: AsyncEngine, **options) -> async_sessionmaker[AsyncSession]:
    import app.core.world_tx  # noqa: F401 — guard записи мира подключается ко всем сессиям (before_flush)

    return async_sessionmaker(engine, expire_on_commit=False, **options)


async def session_scope(maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with maker() as session:
        yield session
