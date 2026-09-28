"""WebSocket-шлюз (ТЗ, раздел 12).

Порядок: подключение → ``auth`` с JWT → ``campaign.join`` с последним полученным ``seq`` →
``state.snapshot`` и досылка пропущенного → ``message.send`` / ``ping``. События следующих этапов
(``turn.pass``, ``vote.cast``, ``entity.inspect``, ``master.tool``) пока отвечают ``error: not_implemented``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import chat
from app.core.campaigns import AccessDenied, Conflict, NotFound, Viewer, get_viewer
from app.core.security import read_token
from app.db.models import Campaign, User
from app.gateway.events import PROTOCOL_VERSION, envelope, publish_message
from app.gateway.hub import Connection

log = logging.getLogger(__name__)
router = APIRouter()

LATER_STAGES = {"turn.pass", "vote.cast", "entity.inspect", "master.tool"}


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
            "messages": [chat.message_payload(m, names) for m in msgs],
            "replay": last_seq is not None,
        },
        seq=c.last_seq,
    )


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
                async with maker() as session:
                    try:
                        viewer = await get_viewer(session, user, conn.campaign_id)
                        conn.seat_id = viewer.seat.id if viewer.seat else None
                        m = await chat.post_message(
                            session,
                            viewer,
                            str(payload.get("kind", "action")),
                            str(payload.get("text", "")),
                            settings.message_max_len,
                        )
                        await session.commit()
                        names = await _names(session, viewer.campaign)
                    except (Conflict, AccessDenied, NotFound) as e:
                        await session.rollback()
                        await conn.send(
                            envelope(
                                "message.rejected",
                                conn.campaign_id,
                                {"reason": str(e), "client_id": payload.get("client_id")},
                            )
                        )
                        continue
                await publish_message(bus, m, names)
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
