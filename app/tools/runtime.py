"""Общее для ИИ-мастера и живого мастера: контекст вызова инструментов, фиксация сообщений, рассылка изменений.

После фиксации транзакции каждое изменение уходит клиентам: ``character.updated`` (публичная часть — всем, полный
лист — месту игрока), ``scene.updated`` (что видно в сцене) и новые сообщения чата (раздел 12).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import campaign_catalog
from app.core import audio, combat, rolls
from app.core.campaigns import master_seat
from app.core.characters import full_view, public_view
from app.core.chat import active_session, next_seq
from app.core.scene_view import VisibleScene, visible_scene
from app.core.world import ZONE_NAMES, World, is_scene_item, load_world
from app.db.models import Campaign, Entity, Message
from app.gateway.events import envelope, publish_message
from app.rules.dice import Dice
from app.tools import audio as _audio_tools  # noqa: F401 — звук сцены
from app.tools import master as _tools  # noqa: F401 — регистрирует инструменты в реестре
from app.tools import plot as _plot_tools  # noqa: F401 — инструменты ведения по каркасу
from app.tools import progress as _progress_tools  # noqa: F401 — опыт и уровни
from app.tools import rest as _rest_tools  # noqa: F401 — отдых и умения с перезарядкой
from app.tools import spells as _spell_tools  # noqa: F401 — сотворение заклинаний
from app.tools.registry import ToolContext

# Кто ещё слушает события хода в этом процессе: например, таймер голосования за отдых (app/gateway/rest.py)
NOTICE_HOOKS: dict[str, Any] = {}


async def open_context(
    session: AsyncSession,
    campaign: Campaign,
    dice: Dice,
    *,
    turn_id: str | None,
    seat_id: str | None,
    focus: str | None = None,
) -> ToolContext:
    """Контекст хода. ``focus`` — место группы разделившегося отряда, ради которой идёт ход."""
    catalog = await campaign_catalog(session, campaign)
    world = await load_world(session, campaign, catalog)
    if focus is not None:
        world.focus = focus
        world.crew = {c.id for c in world.groups().get(focus, [])}
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
    elif is_scene_item(e):
        item["item"] = True
        item["qty"] = int(st.get("qty") or 1)
    return item


def scene_payload(scene, entities: dict, characters: dict, view: VisibleScene) -> dict[str, Any]:
    """Единая сериализация видимой сцены для первичного снимка и обновлений."""
    loc = entities.get(view.current_location_id or "")
    here = view.current_location_id if len(view.place_ids) == 1 else None
    split = party_public(view.groups, entities, here)
    return {
        **({"party": split} if split else {}),
        "location": {"id": loc.id, "name": loc.name} if loc else None,
        "entities": [public_entity(e) for e in view.entities],
        **combat_public(scene, characters, entities, here, len(view.groups) > 1),
    }


def scene_public(
    world: World, place: str | None = None, *, hero_id: str | None = None, is_master: bool = False
) -> dict[str, Any]:
    """Сцена из текущего мира по тем же правилам, что и карта и повторное подключение."""
    if place is not None and hero_id is None:
        hero_id = next(
            (
                h.id
                for h in world.characters.values()
                if world.place_of(h) == place and h.status in ("approved", "active")
            ),
            None,
        )
    view = visible_scene(world.scene, world.entities, world.characters, hero_id=hero_id, is_master=is_master)
    return scene_payload(world.scene, world.entities, world.characters, view)


def combat_public(scene, characters: dict, entities: dict, place: str | None, split: bool) -> dict[str, Any]:
    """Режим, раунд и очередь для зрителя. Бой в другом месте разделившегося отряда его не касается: у него
    свободный режим."""
    if (
        split
        and place is not None
        and scene.mode == "combat"
        and place not in combat.fronts_of(scene, characters, entities)
    ):
        return {"mode": "free", "round": 0, "turn_order": [], "order": [], "turn": None}
    return {
        "mode": scene.mode,
        "round": scene.round,
        "turn_order": scene.turn_order,
        "order": combat.public_order(scene.turn_order, characters, entities),
        "turn": combat.public_turn_of(scene, characters, entities),
    }


def party_public(groups: dict, entities: dict, place: str | None) -> list[dict[str, Any]] | None:
    """Где кто из разделившегося отряда: для плашки «Отряд разделён». ``here`` — место зрителя."""
    if len(groups) <= 1:
        return None
    return [
        {
            "id": p,
            "place": entities[p].name if p in entities else None,
            "names": [h.name for h in heroes],
            "here": place is not None and p == place,
        }
        for p, heroes in groups.items()
    ]


def scene_views(world: World) -> list[tuple[list[str] | None, dict[str, Any]]]:
    """Персональные сцены группируются по одинаковому содержимому, без утечки скрытого мастеру/игрокам."""
    import json

    seats = world.campaign.seats
    if not seats:
        return [(None, scene_public(world))]
    playable = {
        ch.seat_id: ch.id for ch in world.characters.values() if ch.seat_id and ch.status in ("approved", "active")
    }
    out: dict[str, tuple[list[str], dict[str, Any]]] = {}
    for seat in seats:
        master = seat.role == "master"
        view = visible_scene(
            world.scene,
            world.entities,
            world.characters,
            hero_id=None if master else playable.get(seat.id),
            is_master=master,
        )
        payload = scene_payload(world.scene, world.entities, world.characters, view)
        key = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if key in out:
            out[key][0].append(seat.id)
        else:
            out[key] = ([seat.id], payload)
    if len(out) == 1:
        only = next(iter(out.values()))
        # None рассылает всем сокетам, включая владельца без кресла мастера.
        # Это безопасно лишь тогда, когда такой зритель получает те же данные.
        guest = visible_scene(world.scene, world.entities, world.characters, hero_id=None, is_master=False)
        if scene_payload(world.scene, world.entities, world.characters, guest) == only[1]:
            return [(None, only[1])]
    return list(out.values())


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
    for seats, view in scene_views(w):
        await bus.publish(cid, envelope("scene.updated", cid, view), seats)
    for m in messages:
        await publish_message(bus, m, names)
    for kind, payload, seats in ctx.notices:
        await bus.publish(cid, envelope(kind, cid, payload), seats)
        if NOTICE_HOOKS.get(kind):
            NOTICE_HOOKS[kind](cid, payload)
    ctx.notices.clear()
    if "map.changed" in ctx.signals:
        await bus.publish(cid, envelope("map.changed", cid, {}), None)
        ctx.signals.discard("map.changed")
    if "audio" in ctx.signals:
        # после сообщений: эффект звучит, когда игроки уже видят текст хода
        # отряд разделён: каждой группе свой звук, эффекты хода слышит только группа, ради которой он шёл
        place = audio.where(ctx)
        for seats, state in audio.views(ctx.campaign, w.scene, w.groups()):
            mine = (
                place is None
                or seats is None
                or any(h.seat_id in seats for h in w.groups().get(place, []))
                or master_seat(ctx.campaign).id in seats
            )
            payload = {**state, "cues": list(ctx.audio) if mine else []}
            await bus.publish(cid, envelope("audio.state", cid, payload), seats)
        ctx.audio.clear()
        ctx.signals.discard("audio")
