"""Что зритель может сделать прямо сейчас (правило Arty: кнопка видна, только когда действие уместно).

Сервер сам решает, какие действия доступны этому участнику в текущем состоянии, и отдаёт список клиенту
(в ``state.snapshot`` и по запросу ``actions.get``). Клиент рисует только эти кнопки. Для закрытых действий,
которые игрок ожидает увидеть (например, ход в бою), рядом отдаётся причина словами — её показывает поле ввода.
Проверки при самом действии остаются прежними: список — подсказка интерфейсу, а не замена проверок.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.campaigns import Viewer
from app.core.chat import PENDING_REASON, active_session, pending_message
from app.core.world import get_scene
from app.db.models import Character

# session.start — начать сессию (на паузе — продолжить); session.pause; campaign.end — завершить кампанию;
# chat.ooc — писать вне игры; chat.play — действие и речь героя; chat.whisper — шёпот мастеру;
# chat.narrate — повествование живого мастера; turn.pass — пропустить ход; invite.create — пригласить;
# chat.withdraw — отменить ожидающую реплику.


async def available(session: AsyncSession, viewer: Viewer) -> dict[str, Any]:
    c = viewer.campaign
    live = await active_session(session, c.id) is not None
    actions: list[str] = []
    blocked: dict[str, str] = {}
    pending: dict[str, str] | None = None

    if viewer.can_control_session and c.status != "ended":
        actions += ["session.pause"] if live else ["session.start"]
        actions.append("campaign.end")
    if viewer.is_owner and c.status != "ended":
        actions.append("invite.create")

    if viewer.seat is not None or viewer.is_owner:
        actions.append("chat.ooc")
    seat = viewer.seat
    if seat is None or c.status == "ended":
        return {"actions": actions, "blocked": blocked, "pending": pending}

    if not live:
        reason = "Сессия не идёт: пока можно писать только вне игры (//)."
        if seat.role == "player":
            blocked["chat.play"] = reason
        elif seat.occupant_type == "human":
            blocked["chat.narrate"] = reason
        return {"actions": actions, "blocked": blocked, "pending": pending}

    sc = await get_scene(session, c.id)
    in_combat = sc.mode == "combat" and bool(sc.turn_order)
    current = None
    if in_combat:
        entry = sc.turn_order[int((sc.state or {}).get("turn", 0)) % len(sc.turn_order)]
        current = entry["id"]

    if seat.role == "master":
        if seat.occupant_type == "human":
            actions.append("chat.narrate")
            if in_combat:
                actions.append("turn.pass")
        return {"actions": actions, "blocked": blocked, "pending": pending}

    msg = await pending_message(session, c, seat.id)
    if msg is not None:
        pending = {"id": msg.id, "created_at": msg.created_at.isoformat() if msg.created_at else None}
        blocked["chat.play"] = blocked["chat.whisper"] = PENDING_REASON
        actions.append("chat.withdraw")
        if in_combat:
            ch = await session.get(Character, current) if current else None
            if ch is not None and ch.seat_id == seat.id:
                actions.append("turn.pass")
        return {"actions": actions, "blocked": blocked, "pending": pending}

    actions.append("chat.whisper")
    if not in_combat:
        actions.append("chat.play")
        return {"actions": actions, "blocked": blocked, "pending": pending}
    ch = await session.get(Character, current) if current else None
    if ch is not None and ch.seat_id == seat.id:
        if (sc.state or {}).get("submitted"):
            blocked["chat.play"] = "Действие на этот ход уже заявлено: дождитесь ответа мастера."
        else:
            actions.append("chat.play")
        actions.append("turn.pass")
    else:
        who = ch.name if ch is not None else "существ"
        blocked["chat.play"] = f"Идёт бой, сейчас ход: {who}. Пока можно писать вне игры (//) или шёпотом мастеру."
    return {"actions": actions, "blocked": blocked, "pending": pending}
