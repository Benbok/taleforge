"""Saved narrative travel uses known reachable destinations, never map cells."""

from types import SimpleNamespace

from sqlalchemy import select

from app.core.campaigns import Viewer
from app.core.map import party_map
from app.core.object_policy import revealed_to
from app.core.universal.profiles import actor_row
from app.db.models import Campaign, Character, Entity, KnownFact, Seat, User
from app.rules.universal.exploration import EffectChange


async def destination_view(ctx, destination_id):
    actor = await actor_row(ctx.session, ctx.campaign_id, ctx.actor_id)
    if not isinstance(actor, Character):
        raise ValueError("Только герой выбирает переход")
    place = await ctx.session.get(Entity, destination_id)
    if place is None or place.campaign_id != ctx.campaign_id or place.kind != "location":
        raise ValueError("Такого доступного места нет в этом прохождении")
    viewer = Viewer(
        await ctx.session.get(User, ctx.user_id),
        await ctx.session.get(Campaign, ctx.campaign_id),
        await ctx.session.get(Seat, ctx.seat_id),
    )
    view = await party_map(ctx.session, viewer)
    candidates = [exit for exit in view["exits"] if exit.get("id") == destination_id]
    if not candidates or not any(exit.get("state") not in {"closed", "locked"} for exit in candidates):
        raise ValueError("Нет известного открытого пути к выбранному месту")
    passages = [exit for exit in (view.get("sketch") or {}).get("exits", []) if exit.get("to") == destination_id]
    if passages and all(exit.get("state") in {"closed", "locked"} for exit in passages):
        raise ValueError("Известный проход закрыт; сначала его нужно открыть")
    return actor, place, view


async def remember_place(ctx, actor):
    if not actor.location_id:
        return
    from app.core.map_memory import observe_area

    rows = {e.id: e for e in await ctx.session.scalars(select(Entity).where(Entity.campaign_id == ctx.campaign_id))}
    world = SimpleNamespace(
        entities=rows,
        characters={actor.id: actor},
        place_of=lambda h: h.location_id,
        revealed={actor.id: await revealed_to(ctx.session, actor.id)},
        map_known={},
    )
    memory_ctx = SimpleNamespace(
        session=ctx.session, world=world, campaign=await ctx.session.get(Campaign, ctx.campaign_id)
    )
    await observe_area(memory_ctx, actor.location_id, [actor.id])


async def move_hero(ctx, destination_id):
    actor, place, view = await destination_view(ctx, destination_id)
    await remember_place(ctx, actor)
    source_id = (view.get("here") or {}).get("id")
    actor.location_id = place.id
    place.state = {**place.state, "visited_by": sorted(set(place.state.get("visited_by") or []) | {actor.id})}
    await remember_place(ctx, actor)
    fact = await ctx.session.scalar(
        select(KnownFact).where(
            KnownFact.campaign_id == ctx.campaign_id,
            KnownFact.character_id == actor.id,
            KnownFact.subject_id == place.id,
            KnownFact.text == place.description,
        )
    )
    if not fact and place.description:
        ctx.session.add(
            KnownFact(campaign_id=ctx.campaign_id, character_id=actor.id, subject_id=place.id, text=place.description)
        )
    await ctx.session.flush()
    return EffectChange(
        kind="location_changed",
        subject_id=actor.id,
        description=f"{actor.name} переходит в «{place.name}».",
        data=dict(from_id=source_id, to_id=place.id),
    )
