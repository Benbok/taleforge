"""Перезапуск не оставляет иллюстрации «в работе» до конца аренды."""

import asyncio
from datetime import timedelta

from app.core.artwork_recovery import fail_interrupted_artwork
from app.db.models import Entity, LocationArtwork, now
from tests.test_api import make_campaign


def test_restart_closes_pending_artwork_so_it_can_be_retried(client, root):
    cid = make_campaign(client, root)["id"]
    maker = client.app.state.sessionmaker

    async def go():
        async with maker() as s:
            s.add(Entity(id="rec_room", campaign_id=cid, kind="location", name="Поляна", description="Дубы."))
            await s.flush()
            for key, status in (("a", "pending"), ("b", "ready")):
                s.add(
                    LocationArtwork(
                        id=f"la_{key}",
                        campaign_id=cid,
                        location_id="rec_room",
                        request_key=key,
                        source_digest="d",
                        status=status,
                        lease_until=now() + timedelta(minutes=10),
                    )
                )
            await s.commit()
        assert await fail_interrupted_artwork(maker) == 1
        async with maker() as s:
            pending, ready = await s.get(LocationArtwork, "la_a"), await s.get(LocationArtwork, "la_b")
            assert (pending.status, pending.error) == ("failed", "restart")
            assert ready.status == "ready"

    asyncio.run(go())
