"""Сообщения чата и сеансы игры (ТЗ, разделы 5 и 12).

Каждое сообщение кампании получает порядковый номер ``seq``: по нему клиент после переподключения
получает пропущенное. Видимость решает сервер: шёпот видят только автор и мастер.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.campaigns import AccessDenied, Conflict, Viewer, master_seat
from app.core.linker import link_text
from app.db.models import Campaign, GameSession, Message, now

PLAYER_KINDS = ("action", "speech", "whisper", "ooc")
MASTER_KINDS = ("narration", "ooc")
OOC_PREFIX = "//"


def visible(msg: Message, seat_id: str | None) -> bool:
    return msg.visible_to is None or (seat_id is not None and seat_id in msg.visible_to)


def message_payload(msg: Message, names: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "id": msg.id,
        "seq": msg.seq,
        "kind": msg.kind,
        "seat_id": msg.seat_id,
        "author": (names or {}).get(msg.author_user_id or "", None),
        "content": msg.content,
        "whisper": msg.visible_to is not None,
        "data": msg.data,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


async def next_seq(session: AsyncSession, campaign_id: str) -> int:
    """Атомарно увеличивает счётчик кампании: UPDATE ... RETURNING блокирует строку до конца транзакции."""
    stmt = (
        update(Campaign)
        .where(Campaign.id == campaign_id)
        .values(last_seq=Campaign.last_seq + 1)
        .returning(Campaign.last_seq)
    )
    return (await session.execute(stmt)).scalar_one()


async def active_session(session: AsyncSession, campaign_id: str) -> GameSession | None:
    q = select(GameSession).where(GameSession.campaign_id == campaign_id, GameSession.ended_at.is_(None))
    return (await session.scalars(q)).first()


async def post_message(session: AsyncSession, viewer: Viewer, kind: str, text: str, max_len: int) -> Message:
    text = (text or "").strip()
    if text.startswith(OOC_PREFIX):
        kind, text = "ooc", text[len(OOC_PREFIX) :].strip()
    if not text:
        raise Conflict("пустое сообщение")
    if len(text) > max_len:
        raise Conflict(f"сообщение длиннее {max_len} символов")

    seat = viewer.seat
    if seat is None:
        if kind != "ooc":
            raise AccessDenied("без места в кампании доступны только внеигровые сообщения")
    elif seat.role == "master" and kind not in MASTER_KINDS:
        raise Conflict(f"мастер пишет: {', '.join(MASTER_KINDS)}")
    elif seat.role == "player" and kind not in PLAYER_KINDS:
        raise Conflict(f"игрок пишет: {', '.join(PLAYER_KINDS)}")

    game = await active_session(session, viewer.campaign.id)
    if kind != "ooc" and game is None:
        raise Conflict("сессия не запущена: пока доступны только внеигровые сообщения (//)")

    if kind == "narration":
        text = await link_text(session, viewer.campaign.id, text)  # живой мастер тоже получает ссылки на имена

    visible_to = None
    if kind == "whisper":
        visible_to = [seat.id, master_seat(viewer.campaign).id]

    msg = Message(
        campaign_id=viewer.campaign.id,
        session_id=game.id if game else None,
        seq=await next_seq(session, viewer.campaign.id),
        seat_id=seat.id if seat else None,
        author_user_id=viewer.user.id,
        kind=kind,
        visible_to=visible_to,
        content=text,
    )
    session.add(msg)
    await session.flush()
    return msg


async def system_message(session: AsyncSession, campaign: Campaign, text: str, game: GameSession | None) -> Message:
    msg = Message(
        campaign_id=campaign.id,
        session_id=game.id if game else None,
        seq=await next_seq(session, campaign.id),
        kind="system",
        content=text,
    )
    session.add(msg)
    await session.flush()
    return msg


async def history(session: AsyncSession, viewer: Viewer, after_seq: int | None, limit: int) -> list[Message]:
    """Сообщения, видимые этому месту: после ``after_seq`` (досылка) или последние ``limit``."""
    q = select(Message).where(Message.campaign_id == viewer.campaign.id)
    if after_seq is not None:
        rows = (await session.scalars(q.where(Message.seq > after_seq).order_by(Message.seq))).all()
    else:
        rows = list(reversed((await session.scalars(q.order_by(Message.seq.desc()).limit(limit * 4))).all()))
    seat_id = viewer.seat.id if viewer.seat else None
    out = [m for m in rows if visible(m, seat_id)]
    return out if after_seq is not None else out[-limit:]


async def start_session(session: AsyncSession, viewer: Viewer) -> tuple[GameSession, Message]:
    if not viewer.can_control_session:
        raise AccessDenied("запускает сессию владелец или мастер")
    c = viewer.campaign
    if c.status == "ended":
        raise Conflict("кампания завершена")
    if await active_session(session, c.id) is not None:
        raise Conflict("сессия уже идёт")
    game = GameSession(campaign_id=c.id, started_by=viewer.user.id)
    session.add(game)
    c.status = "active"
    await session.flush()
    return game, await system_message(session, c, "Сессия началась.", game)


async def stop_session(session: AsyncSession, viewer: Viewer, reason: str) -> tuple[GameSession, Message]:
    """Пауза или завершение кампании. Голосование игроков за паузу — этап «Офлайн и голосования»."""
    if reason not in ("paused", "ended"):
        raise Conflict("причина: paused или ended")
    if not viewer.can_control_session:
        raise AccessDenied("останавливает сессию владелец или мастер")
    c = viewer.campaign
    game = await active_session(session, c.id)
    if game is None:
        if reason == "ended" and c.status != "ended":
            c.status = "ended"
            await session.flush()
            return None, await system_message(session, c, "Кампания завершена.", None)
        raise Conflict("сессия не запущена")
    game.ended_at, game.end_reason = now(), reason
    c.status = reason
    await session.flush()
    text = "Сессия на паузе." if reason == "paused" else "Кампания завершена."
    return game, await system_message(session, c, text, game)
