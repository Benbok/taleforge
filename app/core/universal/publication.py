"""Publish a completed shared step to all affected players, with per-seat privacy."""

from sqlalchemy import select

from app.core.campaigns import Viewer
from app.core.characters import public_view
from app.core.universal.exploration_views import exploration_game_card
from app.core.universal.scene import universal_scene
from app.db.models import Character, User
from app.gateway.events import envelope


async def publish_game_state(session, bus, campaign):
    cid = campaign.id
    heroes = await session.scalars(
        select(Character).where(Character.campaign_id == cid, Character.status.in_(["active", "approved"]))
    )
    for hero in heroes:
        await bus.publish(cid, envelope("character.updated", cid, {"character": public_view(hero)}), None)
        if hero.seat_id:
            await bus.publish(
                cid,
                envelope("character.sheet", cid, {"character": await exploration_game_card(session, hero)}),
                [hero.seat_id],
            )
    for player in campaign.seats:
        if player.role != "player" or not player.user_id:
            continue
        user = await session.get(User, player.user_id)
        snapshot = await universal_scene(session, campaign, Viewer(user, campaign, player))
        await bus.publish(cid, envelope("scene.updated", cid, snapshot), [player.id])
