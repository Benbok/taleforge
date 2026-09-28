"""WebSocket-шлюз (ТЗ, раздел 12).

Порядок: подключение → ``auth`` с JWT → ``campaign.join`` с последним полученным ``seq`` →
``state.snapshot`` и досылка пропущенного → ``message.send`` / ``ping``. События следующих этапов
(``vote.cast``) пока отвечают ``error: not_implemented``.
``actions.get`` — какие действия доступны сейчас (``state.actions``: actions и blocked, app/core/actions.py).
``entity.inspect`` — карточка сущности по уровню знаний героя (``entity.card``, только этому сокету).
``master.tool`` — инструменты мастера для живого мастера (этап 3). Пошаговый режим (этап 4): в бою пишет только
игрок, чей ход; ``turn.pass`` — пропустить ход (мастер так закрывает ход героя), ``reaction.choose`` — ответ на
кнопку реакции.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import chat, combat
from app.core.actions import available
from app.core.campaigns import AccessDenied, Conflict, NotFound, Viewer, get_viewer
from app.core.security import read_token
from app.db.models import Campaign, Character, Entity, User
from app.gateway.events import PROTOCOL_VERSION, envelope, publish_message
from app.gateway.hub import Connection

log = logging.getLogger(__name__)
router = APIRouter()

LATER_STAGES = {"vote.cast"}
MASTER_TRIGGER_KINDS = ("action", "speech", "whisper")


def _error(code: str, message: str, campaign_id: str | None = None) -> dict[str, Any]:
    return envelope("error", campaign_id, {"code": code, "message": message})


async def _names(session: AsyncSession, campaign: Campaign) -> dict[str, str]:
    return {s.user_id: s.user.name for s in campaign.seats if s.user is not None}


async def _snapshot(session: AsyncSession, viewer: Viewer, last_seq: int | None, hub, history_limit: int) -> dict:
    c = viewer.campaign
    await session.refresh(c, ["last_seq", "status"])
    names = await _names(session, c)
    owner = await session.get(User, c.owner_id)
    names[c.owner_id] = owner.name
    msgs = await chat.history(session, viewer, last_seq, history_limit)
    states = await chat.message_states(session, c, msgs)
    game = await chat.active_session(session, c.id)
    online = hub.online_users(c.id) | {viewer.user.id}
    return envelope(
        "state.snapshot",
        c.id,
        {
            "protocol": PROTOCOL_VERSION,
            "campaign": {"id": c.id, "name": c.name, "status": c.status, "public_intro": c.public_intro},
            "session": {"id": game.id, "started_at": game.started_at.isoformat()} if game else None,
            "me": {
                "user_id": viewer.user.id,
                "seat_id": viewer.seat.id if viewer.seat else None,
                "role": viewer.seat.role if viewer.seat else None,
                "is_owner": viewer.is_owner,
            },
            "seats": [
                {
                    "id": s.id,
                    "role": s.role,
                    "position": s.position,
                    "occupant_type": s.occupant_type,
                    "user_name": s.user.name if s.user else None,
                    "presence": "online" if s.user_id in online else ("offline" if s.user_id else None),
                }
                for s in c.seats
            ],
            "turn": await _turn(session, c.id),
            "heroes": await _heroes(session, c.id),
            "scene": await _scene(session, c),
            **await available(session, viewer),  # actions и blocked: какие кнопки показать этому участнику
            "messages": [chat.message_payload(m, names, states.get(m.id)) for m in msgs],
            "replay": last_seq is not None,
            "collect_window_sec": int((c.settings or {}).get("collect_window_sec", 60)),
        },
        seq=c.last_seq,
    )


async def _heroes(session: AsyncSession, campaign_id: str) -> list[dict]:
    """Публичные части героев отряда: имя, уровень, примерные хиты (полный лист — только своему месту)."""
    from sqlalchemy import select

    from app.core.characters import public_view

    q = select(Character).where(
        Character.campaign_id == campaign_id, Character.status.in_(("approved", "active", "dead"))
    )
    return [public_view(ch) for ch in (await session.scalars(q)).all()]


async def _scene(session: AsyncSession, c: Campaign) -> dict:
    """Сцена для снимка — то же, что ``scene.updated`` (app/tools/runtime.scene_public), но без загрузки
    каталога: только чтение, чтобы вход в кампанию ничего не блокировал."""
    from sqlalchemy import select

    from app.core.world import get_scene
    from app.tools.runtime import public_entity

    sc = await get_scene(session, c.id)
    ents = (await session.scalars(select(Entity).where(Entity.campaign_id == c.id))).all()
    loc = next((e for e in ents if e.id == sc.location_id), None)
    out = [
        public_entity(e)
        for e in ents
        if e.kind != "location" and (sc.location_id is None or e.location_id == sc.location_id)
    ]
    return {
        "mode": sc.mode,
        "round": sc.round,
        "location": {"id": loc.id, "name": loc.name} if loc else None,
        "entities": out,
        "turn_order": sc.turn_order,
        "turn": await _turn(session, c.id),
    }


async def _turn(session: AsyncSession, campaign_id: str) -> dict | None:
    from app.core.world import get_scene

    sc = await get_scene(session, campaign_id)
    if sc.mode != "combat" or not sc.turn_order:
        return None
    st = sc.state or {}
    entry = sc.turn_order[int(st.get("turn", 0)) % len(sc.turn_order)]
    ch = await session.get(Character, entry["id"])
    en = None if ch else await session.get(Entity, entry["id"])
    return {
        "round": sc.round,
        "actor_id": entry["id"],
        "name": ch.name if ch else (en.name if en else "существо"),
        "seat_id": ch.seat_id if ch else None,
        "deadline": st.get("deadline"),
        "submitted": bool(st.get("submitted")),
    }


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    app = ws.app
    settings, maker, hub, bus = app.state.settings, app.state.sessionmaker, app.state.hub, app.state.bus
    await ws.accept()

    # 1. Вход
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=settings.ws_auth_timeout_sec)
    except (TimeoutError, WebSocketDisconnect, ValueError):
        await ws.close(code=4401)
        return
    ok = isinstance(first, dict) and first.get("type") == "auth" and isinstance(first.get("payload"), dict)
    token = first["payload"].get("token") if ok else None
    user_id = read_token(token, settings.jwt_secret) if isinstance(token, str) else None
    async with maker() as session:
        user = await session.get(User, user_id) if user_id else None
    if user is None:
        await ws.send_json(_error("unauthorized", "нужен вход"))
        await ws.close(code=4401)
        return
    await ws.send_json(envelope("auth.ok", None, {"user_id": user.id, "name": user.name}))

    conn: Connection | None = None
    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                await ws.send_json(_error("bad_request", "ожидается объект {type, payload}"))
                continue
            kind = msg.get("type")
            payload = msg.get("payload") or {}

            if kind == "ping":
                await ws.send_json(envelope("pong", None, {}))
                continue

            if kind == "campaign.join":
                campaign_id = payload.get("campaign_id") or msg.get("campaign_id")
                last_seq = payload.get("last_seq")
                async with maker() as session:
                    try:
                        viewer = await get_viewer(session, user, str(campaign_id))
                    except NotFound as e:
                        await ws.send_json(_error("not_found", str(e), campaign_id))
                        continue
                    if conn is not None:
                        hub.remove(conn)
                        await _presence(bus, hub, conn, "offline")
                    conn = Connection(ws, user.id, viewer.campaign.id, viewer.seat.id if viewer.seat else None)
                    snap = await _snapshot(
                        session, viewer, int(last_seq) if last_seq is not None else None, hub, settings.history_on_join
                    )
                    hub.add(conn)
                await conn.send(snap)
                await _presence(bus, hub, conn, "online")
                continue

            if conn is None:
                await ws.send_json(_error("not_joined", "сначала campaign.join"))
                continue

            if kind == "message.send":
                await _send(app, user, conn, payload)
                continue

            if kind == "turn.pass":
                # в фоне: ходы существ могут ждать кнопку реакции от этого же сокета
                _background(_turn_pass(app, user, conn))
                continue

            if kind == "reaction.choose":
                ok = app.state.master.resolve_reaction(
                    str(payload.get("prompt_id")), conn.seat_id, str(payload.get("option", "skip"))
                )
                if not ok:
                    await conn.send(_error("reaction_closed", "время реакции вышло", conn.campaign_id))
                continue

            if kind == "master.tool":
                await _master_tool(app, user, conn, payload)
                continue

            if kind == "actions.get":
                async with maker() as session:
                    viewer = await get_viewer(session, user, conn.campaign_id)
                    await conn.send(envelope("state.actions", conn.campaign_id, await available(session, viewer)))
                continue

            if kind == "entity.inspect":
                await _inspect(maker, user, conn, payload)
                continue

            if kind in LATER_STAGES:
                await conn.send(_error("not_implemented", f"{kind} появится на следующих этапах", conn.campaign_id))
                continue

            await conn.send(_error("unknown_type", f"неизвестное событие {kind!r}", conn.campaign_id))
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("ошибка WebSocket")
    finally:
        if conn is not None:
            hub.remove(conn)
            await _presence(bus, hub, conn, "offline")


async def _master_tool(app, user: User, conn: Connection, payload: dict) -> None:
    """Живой мастер вызывает те же инструменты, что и ИИ-мастер: с той же проверкой и журналом (раздел 7)."""
    from app.tools.plot import run_clock
    from app.tools.registry import execute
    from app.tools.runtime import flush_outbox, open_context, publish_changes

    name, args = payload.get("tool"), payload.get("args") or {}
    request_id = payload.get("request_id")
    async with app.state.sessionmaker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id)
        except NotFound as e:
            await conn.send(_error("not_found", str(e), conn.campaign_id))
            return
        if not viewer.is_master:
            await conn.send(_error("forbidden", "инструменты мастера доступны только месту мастера", conn.campaign_id))
            return
        ctx = await open_context(
            session, viewer.campaign, app.state.dice_factory(), turn_id=None, seat_id=viewer.seat.id
        )
        key = f"live:{viewer.seat.id}:{request_id}" if request_id else None
        result = await execute(ctx, str(name), args if isinstance(args, dict) else {}, key=key)
        if result.get("ok"):
            notes = await run_clock(ctx)  # часы угроз каркаса идут и у живого мастера
            if notes:
                result["plot_clock"] = notes
        messages = await flush_outbox(session, ctx)
        await session.commit()
    await conn.send(envelope("master.tool.result", conn.campaign_id, {"request_id": request_id, **result}))
    if result.get("ok"):
        await publish_changes(app.state.bus, ctx, messages)
        if name == "set_scene_mode":
            if combat.in_combat(ctx):
                _background(app.state.master.advance(conn.campaign_id, "sync"))  # первыми могут ходить существа
            else:
                await app.state.master.after_turn(ctx)


async def _send(app, user: User, conn: Connection, payload: dict) -> None:
    """Реплика игрока: очередь хода в бою → парсер намерений (для действий при ИИ-мастере) → запись в чат."""
    settings, maker, bus = app.state.settings, app.state.sessionmaker, app.state.bus
    # Нативный чат: клиент по умолчанию шлёт kind=auto, тип реплики определяет сервер. Игрок выбирает только шёпот.
    kind, text = str(payload.get("kind") or "auto"), str(payload.get("text", ""))

    async def reject(reason: str) -> None:
        await conn.send(
            envelope("message.rejected", conn.campaign_id, {"reason": reason, "client_id": payload.get("client_id")})
        )

    if kind in ("auto", "action") and text.strip().startswith(chat.OOC_PREFIX):
        kind = "ooc"
    parsed = None
    if kind in ("auto", "action") and text.strip():
        async with maker() as session:
            try:
                viewer = await get_viewer(session, user, conn.campaign_id)
            except NotFound as e:
                await reject(str(e))
                return
            if kind == "auto":
                kind = "narration" if viewer.is_master else "action" if viewer.is_player else "ooc"
            reason = await combat.gate_message(session, viewer, kind, mark=False)
            seat_id = viewer.seat.id if viewer.seat and viewer.is_player else None
            await session.rollback()
        if reason and kind == "action":
            await reject(reason)
            return
        if kind == "action" and seat_id and len(text) <= settings.message_max_len:
            parsed = await app.state.master.parse_intent(conn.campaign_id, seat_id, text)
            if parsed.reject:
                await reject(parsed.reject)
                return
            kind = parsed.kind or kind
    if kind == "auto":
        kind = "action"  # пустой текст: отказ даст проверка сообщения

    async with maker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id)
            conn.seat_id = viewer.seat.id if viewer.seat else None
            reason = await combat.gate_message(session, viewer, kind)
            if reason:
                raise Conflict(reason)
            m = await chat.post_message(session, viewer, kind, text, settings.message_max_len)
            if parsed is not None and parsed.intent and m.kind == "action":
                m.intent = parsed.intent
            await session.commit()
            names = await _names(session, viewer.campaign)
            state = (await chat.message_states(session, viewer.campaign, [m])).get(m.id)
        except (Conflict, AccessDenied, NotFound) as e:
            await session.rollback()
            await reject(str(e))
            return
    await publish_message(bus, m, names, state)
    if parsed is not None and parsed.notice:
        await conn.send(envelope("message.notice", conn.campaign_id, {"text": parsed.notice, "message_id": m.id}))
    if m.kind in MASTER_TRIGGER_KINDS:
        app.state.master.notify(conn.campaign_id)


_tasks: set[asyncio.Task] = set()


def _background(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)

    def done(t: asyncio.Task) -> None:
        _tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            log.error("фоновая задача сокета упала", exc_info=t.exception())

    task.add_done_callback(done)


async def _turn_pass(app, user: User, conn: Connection) -> None:
    """Игрок пропускает свой ход; место мастера так закрывает ход текущего героя."""
    async with app.state.sessionmaker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id)
        except NotFound as e:
            await conn.send(_error("not_found", str(e), conn.campaign_id))
            return
        seat_id = viewer.seat.id if viewer.seat else None
        is_master = viewer.is_master
    reason = "master" if is_master else "pass"
    done = await app.state.master.advance(conn.campaign_id, reason, seat_id=seat_id)
    if done is None:
        await conn.send(_error("not_your_turn", "сейчас не ваш ход", conn.campaign_id))


async def _presence(bus, hub, conn: Connection, status: str) -> None:
    """Онлайн и офлайн. Статус «переподключается» и голосование — этап «Офлайн и голосования»."""
    if conn.seat_id is None:
        return
    if status == "offline" and conn.user_id in hub.online_users(conn.campaign_id):
        return  # ещё открыт другой сокет того же игрока
    try:
        await bus.publish(
            conn.campaign_id,
            envelope("presence.changed", conn.campaign_id, {"seat_id": conn.seat_id, "status": status}),
            None,
        )
    except Exception:  # noqa: BLE001
        log.debug("presence не отправлен", exc_info=True)


async def _inspect(maker, user: User, conn: Connection, payload: dict) -> None:
    from app.core.inspect import InspectError, entity_card

    entity_id = str(payload.get("entity_id") or "")
    async with maker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id)
            card = await entity_card(session, viewer, entity_id)
        except (InspectError, NotFound) as e:
            await conn.send(envelope("entity.card", conn.campaign_id, {"id": entity_id, "error": str(e)}))
            return
    await conn.send(envelope("entity.card", conn.campaign_id, card))
