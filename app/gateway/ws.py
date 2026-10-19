"""WebSocket-шлюз (ТЗ, раздел 12).

Порядок: подключение → ``auth`` с JWT → ``campaign.join`` с последним полученным ``seq`` →
``state.snapshot`` и досылка пропущенного → ``message.send`` / ``ping``.
Офлайн и голосование (этап 8, app/gateway/presence.py): обрыв связи во время сессии — «переподключается», через
60 секунд «офлайн» и ``vote.started``; ``vote.cast`` — голос. Игрок, которому отдали героя ушедшего, действует за
него, передавая ``as_seat`` (место героя) в ``message.send``, ``message.withdraw``, ``turn.pass``,
``reaction.choose``, ``actions.get``, ``entity.inspect``, ``map.get``, ``map.step``, ``map.traverse`` и
``stat.explain``.
``message.withdraw`` — отменить свою ожидающую реплику (``message.withdrawn`` всем, кто её видел).
``message.retry`` — повторить свою реплику, ход по которой упал и откатился (``message.state`` pending всем).
``actions.get`` — какие действия доступны сейчас (``state.actions``: actions и blocked, app/core/actions.py).
``entity.inspect`` — карточка сущности по уровню знаний героя (``entity.card``, только этому сокету).
``map.get`` — схема места и карта открытых мест для героя зрителя (``map.state``, app/core/map.py).
``map.step`` — герой зрителя идёт на нажатую клетку схемы (``map.step.result``, app/tools/movement.py).
``map.traverse`` — герой зрителя проходит проходом комплекса (``map.traverse.result``, app/core/layout/transit.py).
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

from app.agents.intent import arrival_intent
from app.agents.stt import STTError
from app.content.catalog import campaign_catalog
from app.core import chat, combat, voice
from app.core.actions import available
from app.core.campaigns import AccessDenied, Conflict, NotFound, Viewer, get_viewer, stand_in_seats
from app.core.linker import effect_names
from app.core.security import read_token
from app.db.models import Campaign, Character, Entity, User
from app.gateway import rest as rest_votes
from app.gateway.events import PROTOCOL_VERSION, envelope, publish_message
from app.gateway.hub import Connection

log = logging.getLogger(__name__)
router = APIRouter()

MASTER_TRIGGER_KINDS = ("action", "speech", "whisper")


def _error(code: str, message: str, campaign_id: str | None = None) -> dict[str, Any]:
    return envelope("error", campaign_id, {"code": code, "message": message})


async def _names(session: AsyncSession, campaign: Campaign) -> dict[str, str]:
    return {s.user_id: s.user.name for s in campaign.seats if s.user is not None}


async def _snapshot(
    session: AsyncSession, viewer: Viewer, last_seq: int | None, history_limit: int, master=None, presence=None
) -> dict:
    from app.agents import memory

    c = viewer.campaign
    await session.refresh(c, ["last_seq", "status"])
    names = await _names(session, c)
    owner = await session.get(User, c.owner_id)
    names[c.owner_id] = owner.name
    msgs = await chat.history(session, viewer, last_seq, history_limit)
    effects = effect_names(await campaign_catalog(session, c), conditions_only=True) if c.content_chain else {}
    states = await chat.message_states(session, c, msgs)
    game = await chat.active_session(session, c.id)
    seat_id = viewer.seat.id if viewer.seat else None
    last = None if game else await memory.latest(session, c.id)
    scene = await _scene(session, c, viewer)
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
                "stand_in_for": stand_in_seats(c, viewer.user.id),  # чьих героев я веду за ушедших
            },
            "seats": [
                {
                    "id": s.id,
                    "role": s.role,
                    "position": s.position,
                    "occupant_type": s.occupant_type,
                    "user_name": s.user.name if s.user else None,
                    "presence": "online" if s.id == seat_id else presence.status(c.id, s) if presence else None,
                    "stand_in": _stand_in(s),
                }
                for s in c.seats
            ],
            "votes": presence.votes(c.id) if presence else [],
            "rest_votes": await rest_votes.snapshot_votes(
                session, c, seat_id, set(stand_in_seats(c, viewer.user.id)), viewer.is_master
            ),
            "turn": scene["turn"],
            # открытая кнопка реакции переживает переподключение; между сессиями — итог прошлой
            "reaction": master.pending_reaction(c.id, seat_id) if master is not None and seat_id else None,
            "summary": memory.public_summary(last.content) if last is not None else None,
            "heroes": await _heroes(session, c.id),
            "scene": scene,
            "audio": await _audio(session, c, viewer),
            **await available(session, viewer),  # actions и blocked: какие кнопки показать этому участнику
            "messages": [chat.message_payload(m, names, states.get(m.id), effects=effects) for m in msgs],
            "replay": last_seq is not None,
            "collect_window_sec": int((c.settings or {}).get("collect_window_sec", 60)),
        },
        seq=c.last_seq,
    )


def _stand_in(s) -> dict | None:
    """Кто ведёт место, пока его хозяин вне сети: другой игрок или ИИ-мастер."""
    if s.stand_in is not None:
        return {"user_id": s.stand_in.id, "name": s.stand_in.name}
    if s.occupant_type == "agent" and s.delegated_from:
        return {"ai": True, "name": "ИИ-мастер" if s.role == "master" else "ИИ"}
    return None


async def _heroes(session: AsyncSession, campaign_id: str) -> list[dict]:
    """Публичные части героев отряда: имя, уровень, примерные хиты (полный лист — только своему месту)."""
    from sqlalchemy import select

    from app.core.characters import public_view

    q = select(Character).where(
        Character.campaign_id == campaign_id, Character.status.in_(("approved", "active", "dead"))
    )
    entities = {e.id: e for e in (await session.scalars(select(Entity).where(Entity.campaign_id == campaign_id))).all()}
    return [public_view(ch, entities.values()) for ch in (await session.scalars(q)).all()]


async def _scene(session: AsyncSession, c: Campaign, viewer) -> dict:
    """Первичный снимок сцены использует ту же проекцию, что и очередной scene.updated."""
    from sqlalchemy import select

    from app.core.inspect import viewer_hero
    from app.core.scene_view import visible_scene
    from app.core.world import get_scene
    from app.tools.runtime import scene_payload

    sc = await get_scene(session, c.id)
    ents = {e.id: e for e in (await session.scalars(select(Entity).where(Entity.campaign_id == c.id))).all()}
    chars = {ch.id: ch for ch in (await session.scalars(select(Character).where(Character.campaign_id == c.id))).all()}
    hero = None if viewer.is_master else await viewer_hero(session, viewer)
    from app.core.object_policy import revealed_to

    hero_id = hero.id if hero is not None else None
    found = await revealed_to(session, hero_id)
    view = visible_scene(sc, ents, chars, hero_id=hero_id, is_master=viewer.is_master, revealed=found)
    return scene_payload(sc, ents, chars, view)


async def _audio(session: AsyncSession, c: Campaign, viewer) -> dict:
    """Что звучит сейчас: вошедший позже слышит то же, что остальные. Отряд разделён — звук места своего героя."""
    from sqlalchemy import select

    from app.core import audio
    from app.core.inspect import viewer_hero
    from app.core.world import get_scene, party_groups

    sc = await get_scene(session, c.id)
    hero = await viewer_hero(session, viewer)
    if hero is not None:
        chars = (await session.scalars(select(Character).where(Character.campaign_id == c.id))).all()
        if len(party_groups(chars, sc)) > 1:
            return audio.public_state(c, sc, hero.location_id or sc.location_id)
    return audio.public_state(c, sc)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    app = ws.app
    settings, maker, hub = app.state.settings, app.state.sessionmaker, app.state.hub
    presence = app.state.presence
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
                if conn is not None:
                    hub.remove(conn)
                    if conn.campaign_id != str(campaign_id):
                        presence.leave(conn)  # перешёл в другую кампанию; повторный вход в ту же — не уход
                    conn = None
                await presence.before_join(user.id, str(campaign_id))  # вернувшийся забирает место у ИИ
                async with maker() as session:
                    try:
                        viewer = await get_viewer(session, user, str(campaign_id))
                    except NotFound as e:
                        await ws.send_json(_error("not_found", str(e), campaign_id))
                        continue
                    conn = Connection(ws, user.id, viewer.campaign.id, viewer.seat.id if viewer.seat else None)
                    snap = await _snapshot(
                        session,
                        viewer,
                        int(last_seq) if last_seq is not None else None,
                        settings.history_on_join,
                        app.state.master,
                        presence,
                    )
                    # снимок уходит первым: события, опубликованные после добавления в hub, ждут замка отправки
                    await conn.send_lock.acquire()
                    hub.add(conn)
                try:
                    await ws.send_json(snap)
                finally:
                    conn.send_lock.release()
                await presence.joined(conn)
                continue

            if conn is None:
                await ws.send_json(_error("not_joined", "сначала campaign.join"))
                continue

            if kind == "message.send":
                await _send(app, user, conn, payload)
                continue

            if kind == "message.withdraw":
                await _withdraw(app, user, conn, payload)
                continue

            if kind == "message.retry":
                await _retry(app, user, conn, payload)
                continue

            if kind == "turn.pass":
                # в фоне: ходы существ могут ждать кнопку реакции от этого же сокета
                _background(_turn_pass(app, user, conn, payload))
                continue

            if kind == "reaction.choose":
                as_seat = payload.get("as_seat")
                seat_id = as_seat if as_seat and as_seat in conn.stand_in else conn.seat_id
                ok = app.state.master.resolve_reaction(
                    str(payload.get("prompt_id")), seat_id, str(payload.get("option", "skip"))
                )
                if not ok:
                    await conn.send(_error("reaction_closed", "время реакции вышло", conn.campaign_id))
                continue

            if kind == "master.tool":
                await _master_tool(app, user, conn, payload)
                continue

            if kind == "actions.get":
                async with maker() as session:
                    as_seat = payload.get("as_seat")
                    try:
                        viewer = await get_viewer(session, user, conn.campaign_id, as_seat)
                    except NotFound as e:
                        await conn.send(_error("not_found", str(e), conn.campaign_id))
                        continue
                    out = await available(session, viewer)
                if as_seat:
                    out["as_seat"] = as_seat  # что можно герою ушедшего, которого ведёт этот игрок
                await conn.send(envelope("state.actions", conn.campaign_id, out))
                continue

            if kind == "vote.cast":
                reason = await presence.cast(conn, str(payload.get("vote_id") or ""), str(payload.get("option") or ""))
                if reason:
                    await conn.send(_error("vote_rejected", reason, conn.campaign_id))
                continue

            if kind == "rest.ballot":
                reason = await app.state.rest.cast(user, conn, payload)
                if reason:
                    await conn.send(_error("rest_rejected", reason, conn.campaign_id))
                continue

            if kind == "entity.inspect":
                await _inspect(maker, user, conn, payload)
                continue

            if kind == "map.get":
                await _map(maker, user, conn, payload)
                continue

            if kind == "map.step":
                await _step(app, user, conn, payload)
                continue

            if kind == "map.traverse":
                # an authored route between areas travels by route_ref; a Blueprint passage keeps passage_ref
                _background(
                    _route(app, user, conn, payload)
                    if payload.get("route_ref")
                    else _traverse(app, user, conn, payload)
                )
                continue

            if kind == "stat.explain":
                await _explain(maker, user, conn, payload)
                continue

            await conn.send(_error("unknown_type", f"неизвестное событие {kind!r}", conn.campaign_id))
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("ошибка WebSocket")
    finally:
        if conn is not None:
            hub.remove(conn)
            presence.leave(conn)


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
            late = ctx.world.catch_up()  # части отряда сошлись: отставшие по времени догоняют остальных
            if late:
                result["caught_up"] = [{"names": names, "seconds": sec} for names, sec in late]
        messages = await flush_outbox(session, ctx)
        await session.commit()
    await conn.send(envelope("master.tool.result", conn.campaign_id, {"request_id": request_id, **result}))
    if result.get("ok"):
        await publish_changes(app.state.bus, ctx, messages)
        app.state.master.schedule_sketches(ctx)  # describe_place с панели: эскиз строится в фоне
        if (ctx.world.scene.state or {}).get("transits"):  # переход с панели: завершить после подготовки, в фоне
            from app.core.layout import transit

            async def finish_panel():
                async with app.state.master.turn_lock(conn.campaign_id):
                    await transit.complete_queued(
                        app.state.sessionmaker, app.state.master.preparer, app.state.dice_factory, conn.campaign_id,
                        bus=app.state.bus, panel_only=True,
                    )  # fmt: skip

            _background(finish_panel())
        if ctx.operation_refs:  # принятая с панели подготовка мира: исполнитель берёт её сразу, не через 15 с
            app.state.master.signal_recovery()
        # move в бою: герой вошёл в бой или ушёл из него — очередь сдвинулась
        if name == "set_scene_mode" or (name in ("move", "enter_room") and combat.in_combat(ctx)):
            if combat.in_combat(ctx):
                _background(app.state.master.advance(conn.campaign_id, "sync"))  # первыми могут ходить существа
            else:
                await app.state.master.after_turn(ctx)
        else:
            await _publish_turn(app, ctx)


async def _send(app, user: User, conn: Connection, payload: dict) -> None:
    """Реплика игрока: очередь хода в бою → парсер намерений (для действий при ИИ-мастере) → запись в чат."""
    settings, maker, bus = app.state.settings, app.state.sessionmaker, app.state.bus
    # Нативный чат: клиент по умолчанию шлёт kind=auto, тип реплики определяет сервер. Игрок выбирает только шёпот.
    kind, text = str(payload.get("kind") or "auto"), str(payload.get("text", ""))
    as_seat = payload.get("as_seat") or None  # герой ушедшего игрока, которого ведёт этот игрок

    heard: str | None = None  # расшифровка голосовой реплики: при отказе она вернётся игроку в поле ввода

    async def reject(reason: str) -> None:
        body = {"reason": reason, "client_id": payload.get("client_id")}
        if heard:
            body["text"] = heard
        await conn.send(envelope("message.rejected", conn.campaign_id, body))

    # Голосовая реплика: запись уже на сервере, сначала расшифровка, дальше — как обычный текст
    voice_meta = None
    if payload.get("voice"):
        try:
            voice_meta, audio = voice.read(settings.media_dir, conn.campaign_id, str(payload["voice"]))
        except NotFound as e:
            await reject(str(e))
            return
        if voice_meta.get("user_id") != user.id:
            await reject("это чужая запись")
            return
        try:
            result = await app.state.stt.transcribe(audio, voice_meta["mime"])
        except STTError as e:
            await reject(f"голосовое не расшифровано: {e}")
            return
        heard = text = result["text"]
        if not text:
            await reject("речь не распознана: скажите ещё раз громче или ближе к микрофону")
            return
        if kind != "whisper":
            kind = "auto"

    if kind in ("auto", "action") and text.strip().startswith(chat.OOC_PREFIX):
        kind = "ooc"
    parsed = None
    if kind in ("auto", "action") and text.strip():
        async with maker() as session:
            try:
                viewer = await get_viewer(session, user, conn.campaign_id, as_seat)
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
            quick = payload.get("quick")
            if isinstance(quick, dict):
                parsed = await _quick_intent(app, conn.campaign_id, seat_id, quick)
            else:
                parsed = await app.state.master.parse_intent(conn.campaign_id, seat_id, text)
            if parsed.reject:
                await reject(parsed.reject)
                return
            speech_request = (
                isinstance(parsed.intent, dict)
                and isinstance(parsed.intent.get("speech"), str)
                and bool(parsed.intent["speech"].strip())
            )
            needs_recovery = (
                "session_inactive" not in parsed.notes
                and "parser_unavailable" not in parsed.notes
                and parsed.kind not in {"speech", "ooc"}
                and not speech_request
                and (not isinstance(parsed.intent, dict) or not (parsed.intent.get("actions") or []))
            )
            if needs_recovery:
                from types import SimpleNamespace

                from app.agents.master.intent_recovery import recover_message_intent

                recovery = await recover_message_intent(
                    app.state.master,
                    SimpleNamespace(campaign_id=conn.campaign_id, seat_id=seat_id, content=text),
                )
                if recovery.status != "recovered" or recovery.parse_result is None:
                    await reject(recovery.message)
                    return
                parsed = recovery.parse_result
            kind = parsed.kind or kind
    if kind == "auto":
        kind = "action"  # пустой текст: отказ даст проверка сообщения

    async with maker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id, as_seat)
            if not as_seat:
                conn.seat_id = viewer.seat.id if viewer.seat else None
            reason = await combat.gate_message(session, viewer, kind)
            if reason:
                raise Conflict(reason)
            place = payload.get("place") if isinstance(payload.get("place"), str) else None
            m = await chat.post_message(session, viewer, kind, text, settings.message_max_len, place)
            if parsed is not None and parsed.intent and m.kind == "action":
                m.intent = parsed.intent
            if voice_meta is not None:
                clip = {
                    "id": voice_meta["id"],
                    "mime": voice_meta["mime"],
                    "duration": voice.duration(payload.get("duration")),
                }
                m.data = {**(m.data or {}), "voice": clip}
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
    elif m.kind == "narration":
        app.state.master.wake_players(conn.campaign_id)  # живой мастер описал сцену: ИИ-игроки откликаются


async def _withdraw(app, user: User, conn: Connection, payload: dict) -> None:
    """Игрок отменяет ожидающую реплику: она исчезает у всех, автору текст возвращается в поле ввода."""
    maker, bus = app.state.sessionmaker, app.state.bus
    async with maker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id, payload.get("as_seat") or None)
            m = await chat.withdraw_message(session, viewer, str(payload.get("message_id") or ""))
            gone = {"id": m.id, "seq": m.seq}
            text, visible_to = m.content, m.visible_to
            if m.kind == "action":
                await combat.unsubmit(session, viewer)
            await session.commit()
            actions = await available(session, viewer)
        except (Conflict, NotFound) as e:
            await session.rollback()
            await conn.send(envelope("message.rejected", conn.campaign_id, {"reason": str(e)}))
            return
    await bus.publish(conn.campaign_id, envelope("message.withdrawn", conn.campaign_id, gone), visible_to)
    await conn.send(envelope("message.withdrawn", conn.campaign_id, {**gone, "text": text}))
    if payload.get("as_seat"):
        actions["as_seat"] = payload["as_seat"]
    await conn.send(envelope("state.actions", conn.campaign_id, actions))


async def _retry(app, user: User, conn: Connection, payload: dict) -> None:
    """Игрок повторяет реплику упавшего хода: та же реплика снова ждёт мастера, мастер начинает ход."""
    async with app.state.sessionmaker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id, payload.get("as_seat") or None)
            m = await chat.retry_message(
                session,
                viewer,
                str(payload.get("message_id") or ""),
                gate=lambda kind: combat.gate_message(session, viewer, kind),  # в бою — только в свой ход
            )
            await session.commit()
        except (Conflict, NotFound, AccessDenied) as e:
            await session.rollback()
            await conn.send(envelope("message.rejected", conn.campaign_id, {"reason": str(e)}))
            return
    await app.state.bus.publish(
        conn.campaign_id, envelope("message.state", conn.campaign_id, {"ids": [m.id], "state": "pending"}), None
    )
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


async def _turn_pass(app, user: User, conn: Connection, payload: dict) -> None:
    """Игрок пропускает свой ход; место мастера так закрывает ход текущего героя."""
    async with app.state.sessionmaker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id, payload.get("as_seat") or None)
        except NotFound as e:
            await conn.send(_error("not_found", str(e), conn.campaign_id))
            return
        seat_id = viewer.seat.id if viewer.seat else None
        is_master = viewer.is_master
    reason = "master" if is_master else "pass"
    done = await app.state.master.advance(conn.campaign_id, reason, seat_id=seat_id)
    if done is None:
        await conn.send(_error("not_your_turn", "сейчас не ваш ход", conn.campaign_id))


async def _explain(maker, user: User, conn: Connection, payload: dict) -> None:
    """«Почему такое число»: разбор величины своего героя. Чужой лист закрыт, мастер видит любой."""
    from app.content.catalog import campaign_catalog
    from app.core.explain import ExplainError, explain_for

    stat = str(payload.get("stat") or "")
    character_id = str(payload.get("character_id") or "")
    base = {"stat": stat, "character_id": character_id}
    async with maker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id, payload.get("as_seat") or None)
            ch = await session.get(Character, character_id)
            if ch is None or ch.campaign_id != viewer.campaign.id:
                raise ExplainError("нет такого героя")
            mine = viewer.seat is not None and ch.seat_id == viewer.seat.id
            if not (mine or viewer.is_master):
                raise ExplainError("чужой лист закрыт: разбор видит только игрок этого героя и мастер")
            out = await explain_for(session, ch, await campaign_catalog(session, viewer.campaign), stat)
        except (ExplainError, NotFound) as e:
            await conn.send(envelope("stat.explained", conn.campaign_id, {**base, "error": str(e)}))
            return
    await conn.send(envelope("stat.explained", conn.campaign_id, {**base, **out}))


async def _quick_intent(app, campaign_id: str, seat_id: str, quick: dict):
    """Быстрое действие из интерфейса: намерение собрано кнопками, модель его не разбирает, но сервер проверяет
    тем же валидатором, что и ответ парсера (цели и предметы — только из сцены и снаряжения героя)."""
    from app.agents import intent as intents
    from app.tools.runtime import open_context

    acts = quick.get("actions")
    if not isinstance(acts, list) or not acts:
        return intents.ParseResult(reject="быстрое действие пустое")
    raw = {"kind": "action", "actions": acts[:8], "confidence": 1.0}
    async with app.state.sessionmaker() as s:
        c = await s.get(Campaign, campaign_id)
        ctx = await open_context(s, c, app.state.dice_factory(), turn_id=None, seat_id=seat_id)
        ch = next(
            (x for x in ctx.world.characters.values() if x.seat_id == seat_id and x.status in ("approved", "active")),
            None,
        )
        # по ссылке из рассказа карточка места открывается и без карты: «Идти туда» из неё должно проходить
        heard = frozenset()
        if ch is not None:
            from app.core.inspect import mentioned_to_seat

            asked = {
                t for a in acts[:8] if isinstance(a, dict) for t in (a.get("target_id"), *(a.get("target_ids") or []))
            }
            known = intents.action_target_ids(ctx.world, ch)
            found = set()
            for t in asked:
                e = ctx.world.entities.get(t) if isinstance(t, str) else None
                if t not in known and e is not None and e.kind == "location":
                    if await mentioned_to_seat(s, campaign_id, seat_id, t):
                        found.add(t)
            heard = frozenset(found)
        parsed = intents.check(raw, ctx.world, ch, heard) if ch is not None else None
        if parsed is not None and parsed.intent is not None:
            valid_targets = intents.action_target_ids(ctx.world, ch) | heard
            for supplied in acts[:8]:
                targets = [supplied.get("target_id"), *(supplied.get("target_ids") or [])]
                if any(target and target not in valid_targets for target in targets):
                    parsed = intents.ParseResult(reject="Объект сейчас недоступен вашему герою. Обновите сцену.")
                    break
        await s.rollback()
    if parsed is None:
        return intents.ParseResult(reject="у вас нет героя в игре")
    if parsed.intent is None and parsed.reject is None:
        return intents.ParseResult(reject="быстрое действие не прошло проверку")
    return parsed


async def _map(maker, user: User, conn: Connection, payload: dict) -> None:
    from app.core.map import party_map

    async with maker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id, payload.get("as_seat") or None)
            out = await party_map(session, viewer)
        except NotFound as e:
            await conn.send(_error("not_found", str(e), conn.campaign_id))
            return
    out.update(request_id=payload.get("request_id"), as_seat=payload.get("as_seat") or None)
    await conn.send(envelope("map.state", conn.campaign_id, out))


async def _step(app, user: User, conn: Connection, payload: dict) -> None:
    """Игрок нажал клетку схемы: его герой идёт туда (app/tools/movement.py). Ответ ``map.step.result`` — только
    этому сокету; схема у всех обновляется по ``map.changed``."""
    from app.core.inspect import viewer_hero
    from app.core.world_tx import WorldConflict
    from app.tools.movement import hero_step
    from app.tools.registry import ToolError
    from app.tools.runtime import flush_outbox, open_context, publish_changes

    request_id = payload.get("request_id")
    cell = payload.get("cell")

    async def answer(body: dict) -> None:
        await conn.send(envelope("map.step.result", conn.campaign_id, {"request_id": request_id, **body}))

    def cell_ok(c) -> bool:
        return isinstance(c, list) and len(c) == 2 and all(isinstance(x, int) for x in c)

    near = payload.get("near")
    if near is not None and not (isinstance(near, list) and 0 < len(near) <= 64 and all(cell_ok(c) for c in near)):
        await answer({"ok": False, "error": "near — список клеток [столбец, строка]"})
        return
    if near is None and not cell_ok(cell):
        await answer({"ok": False, "error": "клетка — [столбец, строка]"})
        return
    async with app.state.sessionmaker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id, payload.get("as_seat") or None)
        except NotFound as e:
            await answer({"ok": False, "error": str(e)})
            return
        hero = await viewer_hero(session, viewer)
        if hero is None:
            await answer({"ok": False, "error": "у тебя нет героя в этой кампании"})
            return
        ctx = await open_context(session, viewer.campaign, app.state.dice_factory(), turn_id=None, seat_id=None)
        try:
            out = await hero_step(
                ctx,
                hero.id,
                (cell[0], cell[1]) if cell_ok(cell) else None,
                bool(payload.get("confirm")),
                [(c[0], c[1]) for c in near] if near else None,
            )
        except (ToolError, WorldConflict) as e:
            # WorldConflict — мир одновременно изменил другой игрок или ход мастера: отказ этого шага,
            # а не обрыв всего соединения игрока
            await session.rollback()
            await answer({"ok": False, "error": str(e)})
            return
        messages = await flush_outbox(session, ctx)
        try:
            await session.commit()
        except WorldConflict as e:
            await session.rollback()
            await answer({"ok": False, "error": str(e)})
            return
    await answer({"ok": True, **out})
    if out.get("confirm_needed"):
        return
    await publish_changes(app.state.bus, ctx, messages)
    await app.state.bus.publish(conn.campaign_id, envelope("map.changed", conn.campaign_id, {}), None)
    await _publish_turn(app, ctx)


async def _traverse(app, user: User, conn: Connection, payload: dict) -> None:
    """Герой зрителя проходит проходом комплекса: участок за ним сначала готовится, затем сервер заново проверяет
    проход и переводит героя. Ответ ``map.traverse.result`` — только этому сокету; схема у всех — по ``map.changed``."""
    from app.core.inspect import viewer_hero
    from app.core.layout import transit
    from app.tools.runtime import publish_changes

    request_id = payload.get("request_id")
    ref = payload.get("passage_ref")
    source_id = payload.get("source_id")

    async def answer(body: dict) -> None:
        await conn.send(envelope("map.traverse.result", conn.campaign_id, {"request_id": request_id, **body}))

    if not isinstance(ref, str) or not 0 < len(ref) <= 64:
        await answer({"ok": False, "error": "passage_ref — строка"})
        return
    if source_id is not None and (not isinstance(source_id, str) or not 0 < len(source_id) <= 64):
        await answer({"ok": False, "error": "source_id — строка"})
        return
    turn_message = None
    turn_names = None
    try:
        async with app.state.sessionmaker() as session:
            viewer = await get_viewer(session, user, conn.campaign_id, payload.get("as_seat") or None)
            hero = await viewer_hero(session, viewer)
            hero_id = hero.id if hero is not None else None
        if hero_id is None:
            out, published = {"ok": False, "error": "у тебя нет героя в этой кампании"}, []
        else:
            out, published = await transit.traverse(
                app.state.sessionmaker,
                app.state.master.preparer,
                app.state.dice_factory,
                conn.campaign_id,
                hero_id,
                ref,
                expected_source_id=source_id,
            )
            if out.get("moved"):
                try:
                    async with app.state.sessionmaker() as session:
                        viewer = await get_viewer(session, user, conn.campaign_id, payload.get("as_seat") or None)
                        hero = await viewer_hero(session, viewer)
                        game = await chat.active_session(session, conn.campaign_id)
                        if hero is not None and game is not None:
                            turn_message = await chat.post_message(
                                session,
                                viewer,
                                "action",
                                f"Я уже прошёл через «{out['passage']}» и оказался в «{out['area']}». Осматриваюсь.",
                                app.state.settings.message_max_len,
                            )
                            turn_message.intent = arrival_intent(hero.id)
                            turn_message.data = {
                                **(turn_message.data or {}),
                                "map_traverse": {
                                    "event_id": out.get("event_id"),
                                    "area_id": out["area_id"],
                                    "passage": out["passage"],
                                },
                            }
                            turn_names = await _names(session, viewer.campaign)
                            await session.commit()
                except Exception:  # переход уже зафиксирован; сбой запуска мастера не должен отменять его задним числом
                    log.exception("ход мастера после перехода по карте не запущен в кампании %s", conn.campaign_id)
    except NotFound as e:
        out, published = {"ok": False, "error": str(e)}, []
    except Exception:  # noqa: BLE001 — игрок получает ответ и при сбое чтения или первой транзакции
        log.exception("переход игрока в кампании %s не удался", conn.campaign_id)
        out, published = {"ok": False, "error": "переход не удался"}, []
    try:
        await answer(out)
    finally:
        for ctx, messages in published:
            await publish_changes(app.state.bus, ctx, messages)
        if published:
            app.state.master.signal_recovery()  # подготовка вперёд не ждёт 15 с
            await app.state.bus.publish(conn.campaign_id, envelope("map.changed", conn.campaign_id, {}), None)
            await _publish_turn(app, published[-1][0])
        if turn_message is not None:
            await publish_message(app.state.bus, turn_message, turn_names)
            app.state.master.notify(conn.campaign_id)


async def _route(app, user: User, conn: Connection, payload: dict) -> None:
    """Герой зрителя идёт по авторскому маршруту. Сервер сам проверяет порт, доступность и отряд (travel_route);
    неудача — никто не двигается, другой маршрут не подставляется."""
    from app.core.geography.travel import travel_route
    from app.core.inspect import viewer_hero
    from app.tools.runtime import flush_outbox, open_context, publish_changes

    request_id = payload.get("request_id")
    ref = payload.get("route_ref")

    async def answer(body: dict) -> None:
        await conn.send(envelope("map.traverse.result", conn.campaign_id, {"request_id": request_id, **body}))

    if not isinstance(ref, str) or not 0 < len(ref) <= 64:
        await answer({"ok": False, "error": "route_ref — строка"})
        return
    ctx = messages = turn_message = turn_names = None
    try:
        async with app.state.sessionmaker() as session:
            viewer = await get_viewer(session, user, conn.campaign_id, payload.get("as_seat") or None)
            hero = await viewer_hero(session, viewer)
            if hero is None:
                await answer({"ok": False, "error": "у тебя нет героя в этой кампании"})
                return
            campaign = await session.get(Campaign, conn.campaign_id)
            ctx = await open_context(session, campaign, app.state.dice_factory(), turn_id=None, seat_id=None)
            result = await travel_route(ctx, ref, [hero.id], action_ref={"source": "map", "request_id": request_id})
            if result.failure_code:
                await session.rollback()
                await answer({"ok": False, "moved": False, "reason": result.failure_code})
                return
            area = ctx.world.entities[result.destination_area_id]
            messages = await flush_outbox(session, ctx)
            game = await chat.active_session(session, conn.campaign_id)
            if game is not None:
                turn_message = await chat.post_message(
                    session,
                    viewer,
                    "action",
                    f"Я прошёл по пути и оказался в «{area.name}». Осматриваюсь.",
                    app.state.settings.message_max_len,
                )
                turn_message.intent = arrival_intent(hero.id)
                turn_message.data = {**(turn_message.data or {}), "map_travel": {"route_id": ref, "area_id": area.id}}
                turn_names = await _names(session, viewer.campaign)
            await session.commit()
    except NotFound as e:
        await answer({"ok": False, "error": str(e)})
        return
    except Exception:  # noqa: BLE001 — игрок получает ответ и при сбое
        log.exception("переход по маршруту в кампании %s не удался", conn.campaign_id)
        await answer({"ok": False, "error": "переход не удался"})
        return
    await answer({"ok": True, "moved": True, "area_id": area.id, "area": area.name, "passage": ref})
    await publish_changes(app.state.bus, ctx, messages)
    await app.state.bus.publish(conn.campaign_id, envelope("map.changed", conn.campaign_id, {}), None)
    if turn_message is not None:
        await publish_message(app.state.bus, turn_message, turn_names)
        app.state.master.notify(conn.campaign_id)


async def _publish_turn(app, ctx) -> None:
    """В бою — свежий остаток хода героя (действие, бонусное действие, шаги) всем, кто видит этот ход."""
    if not combat.in_combat(ctx):
        return
    cid = ctx.campaign.id
    for seats, view in combat.turn_views(ctx.world):
        await app.state.bus.publish(cid, envelope("turn.changed", cid, {"turn": view}), seats)


async def _inspect(maker, user: User, conn: Connection, payload: dict) -> None:
    from app.core.inspect import InspectError, entity_card

    entity_id = str(payload.get("entity_id") or "")
    async with maker() as session:
        try:
            viewer = await get_viewer(session, user, conn.campaign_id, payload.get("as_seat") or None)
            card = await entity_card(session, viewer, entity_id)
        except (InspectError, NotFound) as e:
            await conn.send(envelope("entity.card", conn.campaign_id, {"id": entity_id, "error": str(e)}))
            return
    await conn.send(envelope("entity.card", conn.campaign_id, card))
