"""Общее для ИИ-мастера и живого мастера: контекст вызова инструментов, фиксация сообщений, рассылка изменений.

После фиксации транзакции каждое изменение уходит клиентам: ``character.updated`` (публичная часть — всем, полный
лист — месту игрока), ``scene.updated`` (что видно в сцене) и новые сообщения чата (раздел 12).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import campaign_catalog
from app.core import audio, combat, rolls
from app.core.characters import full_view, public_view
from app.core.chat import active_session, next_seq
from app.core.world import ZONE_NAMES, World, load_world
from app.db.models import Campaign, Entity, Message
from app.gateway.events import envelope, publish_message
from app.rules.dice import Dice
from app.tools import audio as _audio_tools  # noqa: F401 — звук сцены
from app.tools import master as _tools  # noqa: F401 — регистрирует инструменты в реестре
from app.tools import plot as _plot_tools  # noqa: F401 — инструменты ведения по каркасу
from app.tools.registry import ToolContext


async def open_context(
    session: AsyncSession, campaign: Campaign, dice: Dice, *, turn_id: str | None, seat_id: str | None
) -> ToolContext:
    catalog = await campaign_catalog(session, campaign)
    world = await load_world(session, campaign, catalog)
    game = await active_session(session, campaign.id)
    return ToolContext(
        session=session,
        campaign=campaign,
        world=world,
        dice=dice,
        game_session_id=game.id if game else None,
        turn_id=turn_id,
        actor_seat_id=seat_id,
    )


async def flush_outbox(session: AsyncSession, ctx: ToolContext) -> list[Message]:
    """Карточки открытых бросков хода и сообщения, которые инструменты отложили до конца хода (шёпот), получают
    номера и пишутся в чат. Вызывается до повествования, поэтому числа в чате появляются раньше слов."""
    audio.finalize(ctx)  # короткие фразы на гибель героя и раскрытую тайну — до фиксации хода
    out = []
    heroes = set(ctx.world.characters)
    for ev in ctx.events:
        if ev.id in ctx.carded or ev not in session:
            continue
        ctx.carded.add(ev.id)
        data = rolls.card(ev, heroes)
        if data is None:
            continue
        for x in data.get("order") or []:
            who = ctx.world.characters.get(x["id"]) or ctx.world.entities.get(x["id"])
            x["name"] = who.name if who else None
        msg = Message(
            campaign_id=ctx.campaign.id,
            session_id=ctx.game_session_id,
            seq=await next_seq(session, ctx.campaign.id),
            seat_id=ctx.actor_seat_id,
            kind="roll",
            content=rolls.line(data, {x["id"]: x["name"] for x in data.get("order") or [] if x.get("name")}),
            data=data,
        )
        session.add(msg)
        out.append(msg)
    for m in ctx.outbox:
        msg = Message(
            campaign_id=ctx.campaign.id,
            session_id=ctx.game_session_id,
            seq=await next_seq(session, ctx.campaign.id),
            seat_id=m.get("seat_id"),
            kind=m["kind"],
            visible_to=m.get("visible_to"),
            content=m["content"],
        )
        session.add(msg)
        out.append(msg)
    ctx.outbox.clear()
    await session.flush()
    return out


def public_entity(e: Entity) -> dict[str, Any]:
    """Сущность сцены, как её видят игроки: у существ — состояние словами и отношение, без чисел."""
    item: dict[str, Any] = {"id": e.id, "name": e.name, "kind": e.kind, "zone": ZONE_NAMES.get(e.zone, e.zone)}
    st = e.state or {}
    if e.kind == "creature":
        hp, mx = st.get("hp"), st.get("hp_max")
        if st.get("dead"):
            item["condition"] = "мёртв"
        elif hp is not None and mx:
            item["condition"] = "невредим" if hp >= mx else "ранен" if hp > mx / 2 else "тяжело ранен"
        item["attitude"] = st.get("attitude", "hostile")
    return item


def scene_public(world: World) -> dict[str, Any]:
    """Сцена, как её видят игроки: имена, зоны и примерное состояние, без чисел существ (раздел 10)."""
    loc = world.entities.get(world.scene.location_id or "")
    ents = [public_entity(e) for e in world.in_scene_entities()]
    return {
        "mode": world.scene.mode,
        "round": world.scene.round,
        "location": {"id": loc.id, "name": loc.name} if loc else None,
        "entities": ents,
        "turn_order": world.scene.turn_order,
        "order": combat.public_order(world.scene.turn_order, world.characters, world.entities),
        "turn": combat.public_turn(world),
    }


async def publish_changes(bus, ctx: ToolContext, messages: list[Message], names: dict[str, str] | None = None):
    cid = ctx.campaign.id
    w = ctx.world
    for i in sorted(ctx.changed):
        ch = w.characters.get(i)
        if ch is None:
            continue
        await bus.publish(cid, envelope("character.updated", cid, {"character": public_view(ch)}), None)
        if ch.seat_id:
            full = full_view(ch, w.catalog, w.inventory.get(ch.id, []), w.effects)
            ev = next((e.id for e in reversed(ctx.events) if i in (e.actor_id, e.target_id)), None)
            await bus.publish(cid, envelope("character.sheet", cid, {"character": full, "event_id": ev}), [ch.seat_id])
    for ev in ctx.events:
        # «Вы узнали больше о…»: плашка только тому, кто узнал
        ch = w.characters.get(ev.actor_id or "")
        if ev.tool in ("reveal_knowledge", "learn_fact") and ch is not None and ch.seat_id:
            en = w.entities.get(ev.target_id or "") or w.characters.get(ev.target_id or "")
            level = (ev.payload or {}).get("level")
            info = {"entity_id": ev.target_id, "name": en.name if en else None, "level": level}
            await bus.publish(cid, envelope("knowledge.revealed", cid, info), [ch.seat_id])
    await bus.publish(cid, envelope("scene.updated", cid, scene_public(w)), None)
    for m in messages:
        await publish_message(bus, m, names)
    if "audio" in ctx.signals:
        # после сообщений: эффект звучит, когда игроки уже видят текст хода
        payload = {**audio.public_state(ctx.campaign, w.scene), "cues": list(ctx.audio)}
        await bus.publish(cid, envelope("audio.state", cid, payload), None)
        ctx.audio.clear()
        ctx.signals.discard("audio")
