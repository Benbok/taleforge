"""Post-commit outbox delivery, with no ORM/game objects held during inference."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import audio
from app.core.chat import active_session
from app.core.world import party_groups
from app.db.models import Campaign, Character, Entity, Scene, Seat, SfxAsset, SfxPlayback, SfxSound
from app.db.models import now as utc_now
from app.gateway.events import envelope
from app.sfx.service import track
from app.sfx.storage import asset_path

log = logging.getLogger(__name__)


def stamp(scene, characters, place: str | None, session_id: str | None) -> dict:
    groups = party_groups(characters, scene)
    return {
        "location_id": scene.location_id,
        "place_id": place,
        "mode": scene.mode,
        "round": scene.round,
        "game_time": scene.game_time,
        "session_id": session_id,
        "members": sorted((c.id, c.seat_id, c.location_id or scene.location_id) for c in groups.get(place, [])),
        "groups": sorted(str(p) for p in groups),
    }


def context_of(ctx) -> dict:
    groups = ctx.world.groups()
    place = ctx.world.focus or (next(iter(groups)) if len(groups) == 1 else ctx.world.scene.location_id)
    # JSON normalizes tuple entries into lists, so use the same representation for comparisons.
    value = stamp(ctx.world.scene, ctx.world.characters.values(), place, ctx.game_session_id)
    value["members"] = [list(row) for row in value["members"]]
    return value


def audience_of(ctx, context: dict) -> list[str]:
    groups = ctx.world.groups()
    if len(groups) <= 1:
        return [s.id for s in ctx.campaign.seats]
    seats = [c.seat_id for c in groups.get(context["place_id"], []) if c.seat_id]
    seats += [s.id for s in ctx.campaign.seats if s.role == "master"]
    return sorted(set(seats))


async def prepare_playbacks(ctx) -> None:
    """Freeze the final action context inside the turn transaction, before narration/checkpoint."""
    if not ctx.sfx_requests:
        return
    final = context_of(ctx)
    for row in (
        await ctx.session.scalars(
            select(SfxPlayback).where(SfxPlayback.id.in_(ctx.sfx_requests), SfxPlayback.status == "pending")
        )
    ).all():
        if row.context["place_id"] != final["place_id"] or row.context["members"] != final["members"]:
            row.status = "skipped"
        else:
            row.context, row.audience = final, audience_of(ctx, final)


async def arm(ctx) -> None:
    """Called after publish_changes sent narration; works when the original session has already closed."""
    if not ctx.sfx_requests:
        return
    cfg = ctx.session.info.get("settings", Settings())
    context = context_of(ctx)
    async with AsyncSession(bind=ctx.session.bind, expire_on_commit=False) as session:
        rows = (
            await session.scalars(
                select(SfxPlayback).where(SfxPlayback.id.in_(ctx.sfx_requests), SfxPlayback.status == "pending")
            )
        ).all()
        for row in rows:
            if row.context != context:
                row.status = "skipped"
                continue
            row.status, row.expires_at = "armed", time.time() + cfg.sfx_playback_ttl
        await session.commit()
    ctx.sfx_requests.clear()


class Delivery:
    def __init__(self, maker, settings: Settings, bus):
        self.maker, self.settings, self.bus = maker, settings, bus
        self.task: asyncio.Task | None = None

    async def tick(self) -> int:
        count = 0
        async with self.maker() as session:
            await session.execute(
                update(SfxPlayback)
                .where(SfxPlayback.status == "pending", SfxPlayback.created_at < utc_now() - timedelta(minutes=10))
                .values(status="skipped")
            )
            await session.commit()
            rows = (
                await session.scalars(
                    select(SfxPlayback).where(SfxPlayback.status == "armed").order_by(SfxPlayback.created_at).limit(32)
                )
            ).all()
            for row in rows:
                now = time.time()
                campaign = await session.get(Campaign, row.campaign_id, populate_existing=True)
                scene = await session.get(Scene, row.campaign_id, populate_existing=True)
                chars = (await session.scalars(select(Character).where(Character.campaign_id == row.campaign_id))).all()
                game = await active_session(session, row.campaign_id) if campaign else None
                current = stamp(scene, chars, row.context["place_id"], game.id if game else None) if scene else None
                if current:
                    current["members"] = [list(item) for item in current["members"]]
                valid = bool(
                    campaign
                    and scene
                    and audio.enabled(campaign)
                    and (
                        row.asset_id is not None
                        or (self.settings.sfx_enabled and (campaign.settings or {}).get("sfx_enabled"))
                    )
                    and now <= row.expires_at
                    and current == row.context
                    and campaign.status == "active"
                )
                if not valid:
                    await session.execute(
                        update(SfxPlayback)
                        .where(SfxPlayback.id == row.id, SfxPlayback.status == "armed")
                        .values(status="skipped")
                    )
                    await session.commit()
                    continue
                sound = await session.get(SfxSound, row.sound_id)
                asset_id = row.asset_id or (sound.current_asset_id if sound else None)
                asset = await session.get(SfxAsset, asset_id) if asset_id else None
                if not asset or not asset_path(self.settings, asset.id).is_file():
                    continue
                # Claim before publish: a crash may skip a sound, but cannot replay an old one on reconnect.
                claimed = await session.execute(
                    update(SfxPlayback)
                    .where(SfxPlayback.id == row.id, SfxPlayback.status == "armed")
                    .values(status="sent", asset_id=asset.id)
                )
                await session.commit()
                if not claimed.rowcount:
                    continue
                from app.tools.runtime import combat_public

                entities = (await session.scalars(select(Entity).where(Entity.campaign_id == row.campaign_id))).all()
                projected = combat_public(
                    scene,
                    {c.id: c for c in chars},
                    {e.id: e for e in entities},
                    row.context["place_id"],
                    len(party_groups(chars, scene)) > 1,
                )
                payload = {
                    "event_id": row.id,
                    "request_id": row.id,
                    "asset_id": asset.id,
                    "track": track(sound, asset),
                    "duration_seconds": asset.duration_seconds,
                    "place_id": row.context["place_id"],
                    "mode": row.context["mode"],
                    "round": row.context["round"],
                    "now": now,
                    "expires_at": row.expires_at,
                }
                if (projected["mode"], projected["round"]) == (scene.mode, scene.round):
                    audiences = [(list(row.audience), payload)]
                else:
                    masters = set(
                        (
                            await session.scalars(
                                select(Seat.id).where(Seat.campaign_id == row.campaign_id, Seat.role == "master")
                            )
                        ).all()
                    )
                    audiences = [
                        ([s for s in row.audience if s in masters], payload),
                        (
                            [s for s in row.audience if s not in masters],
                            {**payload, "mode": projected["mode"], "round": projected["round"]},
                        ),
                    ]
                for seats, event in audiences:
                    if seats:
                        await self.bus.publish(
                            row.campaign_id, envelope("audio.sfx_ready", row.campaign_id, event), seats
                        )
                count += 1
        return count

    async def run(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("SFX delivery unavailable; game continues")
            await asyncio.sleep(0.25)

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
