"""The synchronous test harness uses multiple event loops for one app engine."""

import asyncio

from sqlalchemy import text

from app.db.session import make_sessionmaker


def test_app_engine_can_be_inspected_across_test_loops(client):
    maker = make_sessionmaker(client.app.state.engine)

    async def inspect():
        async with maker() as session:
            return await session.scalar(text("SELECT 1"))

    assert asyncio.run(inspect()) == 1
    assert asyncio.run(inspect()) == 1
