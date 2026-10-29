import asyncio
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.artwork_recovery import fail_interrupted_artwork
from app.db.models import Artwork, now
from tests.test_api import make_campaign


def row(cid, key, status, subject="s1", kind="map_backdrop"):
    return Artwork(
        campaign_id=cid, kind=kind, subject_id=subject, request_key=key, source_digest="d", status=status,
        lease_until=now() + timedelta(minutes=10),
    )


def test_artwork_table_rejects_two_pending_for_one_subject(client, root):
    cid = make_campaign(client, root)["id"]
    maker = client.app.state.sessionmaker

    async def go():
        async with maker() as s:
            s.add_all([row(cid, "a", "pending"), row(cid, "b", "ready"), row(cid, "c", "pending", subject="s2")])
            await s.commit()
        async with maker() as s:
            s.add(row(cid, "d", "pending"))
            with pytest.raises(IntegrityError):
                await s.commit()

    asyncio.run(go())


def test_restart_closes_pending_generic_artwork(client, root):
    cid = make_campaign(client, root)["id"]
    maker = client.app.state.sessionmaker

    async def go():
        async with maker() as s:
            s.add_all([row(cid, "a", "pending"), row(cid, "b", "ready")])
            await s.commit()
        assert await fail_interrupted_artwork(maker) == 1
        async with maker() as s:
            rows = {a.request_key: a for a in (await s.execute(__import__("sqlalchemy").select(Artwork))).scalars()}
            assert (rows["a"].status, rows["a"].error) == ("failed", "restart") and rows["b"].status == "ready"

    asyncio.run(go())
