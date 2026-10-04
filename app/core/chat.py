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
from app.core.world import get_scene, party_groups
from app.db.models import Campaign, Character, GameSession, MasterTurn, Message, now

PLAYER_KINDS = ("action", "speech", "whisper", "ooc")
MASTER_KINDS = ("narration", "ooc")
OOC_PREFIX = "//"
PENDING_KINDS = ("action", "speech", "whisper")  # реплики, на которые отвечает ИИ-мастер
TURN_KINDS = ("action", "speech")  # реплики, которые берёт ход мастера; шёпот мастер отвечает вне хода
# Состояние шёпота мастеру в data["answer"]: ход его не берёт, поэтому статус живёт на самом сообщении
WHISPER_STATES = ("pending", "processing", "answered", "failed")
PENDING_REASON = "Ваша реплика ждёт мастера. Отмените её, чтобы написать другую, или пишите вне игры через //."
TURN_STATES = {"running": "processing", "done": "answered", "failed": "failed"}


def visible(msg: Message, seat_id: str | None) -> bool:
    return msg.visible_to is None or (seat_id is not None and seat_id in msg.visible_to)


def message_payload(msg: Message, names: dict[str, str] | None = None, state: str | None = None) -> dict[str, Any]:
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
        "state": state,
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

    visible_to = data = None
    if kind == "whisper":
        visible_to = [seat.id, master_seat(viewer.campaign).id]
        data = {"answer": "pending"}  # ИИ-мастер ответит на него сразу и только автору (answer_whispers)
    elif kind in ("action", "speech") and seat is not None and seat.role == "player":
        # отряд разделён: реплику слышат только герои в том же месте и мастер (design/party-split.md)
        group = await group_of(session, viewer.campaign, seat.id)
        if group is not None:
            data = {"place": group[0]}
            visible_to = group[1]

    msg = Message(
        campaign_id=viewer.campaign.id,
        session_id=game.id if game else None,
        seq=await next_seq(session, viewer.campaign.id),
        seat_id=seat.id if seat else None,
        author_user_id=viewer.user.id,
        kind=kind,
        visible_to=visible_to,
        content=text,
        data=data,
    )
    session.add(msg)
    await session.flush()
    return msg


async def party(session: AsyncSession, campaign: Campaign) -> dict[str | None, list[Character]]:
    """Герои отряда по местам: одна запись — отряд вместе, несколько — разделился."""
    scene = await get_scene(session, campaign.id)
    chars = (await session.scalars(select(Character).where(Character.campaign_id == campaign.id))).all()
    return party_groups(chars, scene)


def audience(campaign: Campaign, heroes: list[Character]) -> list[str]:
    """Кто видит сообщения группы: места её героев и мастер."""
    return [*dict.fromkeys(h.seat_id for h in heroes if h.seat_id), master_seat(campaign).id]


async def group_of(session: AsyncSession, campaign: Campaign, seat_id: str) -> tuple[str | None, list[str]] | None:
    """Место героя этого игрока и кто его слышит, если отряд разделён; ``None`` — отряд вместе или героя нет."""
    groups = await party(session, campaign)
    if len(groups) <= 1:
        return None
    for place, heroes in groups.items():
        if any(h.seat_id == seat_id for h in heroes):
            return place, audience(campaign, heroes)
    return None


def whisper_state(msg: Message) -> str | None:
    """Состояние шёпота мастеру; None — шёпот старше ответа вне хода, его статус считается по ходам."""
    if msg.kind != "whisper":
        return None
    state = (msg.data or {}).get("answer")
    return state if state in WHISPER_STATES else None


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
    """Пауза или завершение кампании владельцем или мастером. Пауза по голосованию — app/gateway/presence.py."""
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
    text = "Сессия на паузе." if reason == "paused" else "Кампания завершена."
    return game, await close_session(session, c, game, reason, text)


async def close_session(session: AsyncSession, c: Campaign, game: GameSession, reason: str, text: str) -> Message:
    """Закрыть идущую сессию: пауза или конец. Замещения на время офлайна (раздел 11) заканчиваются вместе с ней."""
    game.ended_at, game.end_reason = now(), reason
    c.status = reason
    release_stand_ins(c)
    await session.flush()
    return await system_message(session, c, text, game)


def release_stand_ins(c: Campaign) -> list[str]:
    """Вернуть места хозяевам: герой — своему игроку, место мастера — живому мастеру. Возвращает id мест."""
    back = []
    for s in c.seats:
        if s.stand_in_user_id is not None:
            s.stand_in_user_id = None
            back.append(s.id)
        if s.role == "master" and s.occupant_type == "agent" and s.delegated_from and s.delegated_from == s.user_id:
            s.occupant_type, s.delegated_from = "human", None
            back.append(s.id)
    return back


async def _ai_live(session: AsyncSession, campaign: Campaign) -> bool:
    return master_seat(campaign).occupant_type == "agent" and await active_session(session, campaign.id) is not None


async def pending_message(session: AsyncSession, campaign: Campaign, seat_id: str | None) -> Message | None:
    """Реплика места, которую ИИ-мастер ещё не взял: действие или речь вне хода, шёпот без ответа.
    Только при ИИ-мастере и идущей сессии."""
    if seat_id is None or master_seat(campaign).occupant_type != "agent":
        return None
    game = await active_session(session, campaign.id)
    if game is None:
        return None
    q = (
        select(Message)
        .where(Message.campaign_id == campaign.id, Message.seat_id == seat_id, Message.kind.in_(PENDING_KINDS))
        .order_by(Message.seq.desc())
        .limit(20)
    )
    waiting = []
    for m in (await session.scalars(q)).all():
        state = whisper_state(m)
        # шёпот прошлой сессии уже не ждёт: ответ даётся только в идущей
        if state is None and m.turn_id is None or state in ("pending", "processing") and m.session_id == game.id:
            waiting.append(m)
    return min(waiting, key=lambda m: m.seq) if waiting else None


async def message_states(session: AsyncSession, campaign: Campaign, msgs: list[Message]) -> dict[str, str]:
    """Статус реплик игроков при ИИ-мастере: по ходу, который взял реплику (``messages.turn_id``)."""
    if master_seat(campaign).occupant_type != "agent":
        return {}
    players = {s.id for s in campaign.seats if s.role == "player"}
    mine = [m for m in msgs if m.kind in PENDING_KINDS and m.seat_id in players]
    if not mine:
        return {}
    ids = {m.turn_id for m in mine if m.turn_id}
    status: dict[str, str] = {}
    if ids:
        q = select(MasterTurn.id, MasterTurn.status).where(MasterTurn.id.in_(ids))
        status = dict((await session.execute(q)).all())
    game = await active_session(session, campaign.id)
    live = game is not None
    out: dict[str, str] = {}
    for m in mine:
        if (state := whisper_state(m)) is not None:
            if state != "pending" or live and m.session_id == game.id:
                out[m.id] = state
            continue
        if m.turn_id is None:
            if live:
                out[m.id] = "pending"
        else:
            out[m.id] = TURN_STATES.get(status.get(m.turn_id, "done"), "answered")
    return out


async def withdraw_message(session: AsyncSession, viewer: Viewer, message_id: str) -> Message:
    """Игрок отменяет свою реплику, пока её не взял ход ИИ-мастера. Реплика удаляется."""
    m = await session.get(Message, message_id)
    seat = viewer.seat
    if (
        m is None
        or m.campaign_id != viewer.campaign.id
        or seat is None
        or m.seat_id != seat.id
        or m.kind not in PENDING_KINDS
        or not await _ai_live(session, viewer.campaign)
    ):
        raise Conflict("Эту реплику отменить нельзя.")
    state = whisper_state(m)
    taken = state != "pending" if state is not None else m.turn_id is not None
    if taken:
        raise Conflict("Мастер уже отвечает на эту реплику.")
    await session.delete(m)
    await session.flush()
    return m
