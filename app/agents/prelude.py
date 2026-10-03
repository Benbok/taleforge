"""Перед игрой (проект «Подготовка кампании», разделы 5 и 7.1): вопросы о связях героев, личные крючки и вступление.

Всё это делает ИИ-мастер на своей модели и только когда у кампании есть каркас: вопросы и вступление опираются
на завязку и первый узел. У живого мастера герои получают вопросы по умолчанию, а вступление он пишет сам.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select

from app.agents.llm import LLMError
from app.content.catalog import campaign_catalog
from app.core import bonds, plot
from app.core.campaigns import master_seat
from app.core.chat import active_session, next_seq
from app.core.linker import link_text
from app.db.models import AgentConfig, Campaign, CampaignSecret, Character, LlmCall, Message, Scene
from app.gateway.events import envelope, publish_message

log = logging.getLogger(__name__)

ATTEMPTS = 2
QUESTIONS_TOOL = "submit_bond_questions"
HOOK_TOOL = "submit_hook"
PLAYING = ("approved", "active")
MARKUP = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")


async def _ai_plan(s, c: Campaign) -> tuple[AgentConfig | None, dict]:
    """(настройки ИИ-мастера, каркас) или (None, {}), если мастер — человек или каркаса нет."""
    seat = master_seat(c)
    if seat.occupant_type != "agent" or not seat.agent_config_id:
        return None, {}
    secret = await s.get(CampaignSecret, c.id)
    if secret is None or not plot.has_plan(secret.plot):
        return None, {}
    return await s.get(AgentConfig, seat.agent_config_id), secret.plot


async def _names(s, c: Campaign, ch: Character) -> tuple[str, str]:
    cat = await campaign_catalog(s, c)
    out = []
    for key, kind in (("class_id", "class"), ("origin_id", "origin")):
        rec = cat.find((ch.sheet or {}).get(key) or "", kind)
        out.append(rec.name if rec else "")
    return out[0], out[1]


async def _hero(s, c: Campaign, ch: Character, *, private: bool) -> str:
    cls, origin = await _names(s, c, ch)
    traits = "; ".join(f"{k}: {v}" for k, v in (ch.personality or {}).items() if v and k != "bonds")
    parts = [f"{ch.name} ({ch.id}): {cls}, {origin}, уровень {(ch.sheet or {}).get('level', 1)}."]
    if ch.public_bio:
        parts.append(f"О себе: {ch.public_bio}")
    if traits:
        parts.append(f"Характер: {traits}")
    if private and ch.private_backstory:
        parts.append(f"Личная предыстория (тайна игрока): {ch.private_backstory}")
    answers = bonds.render(ch, private=private)
    if answers:
        parts.append("Ответы о связях:\n" + answers)
    return "\n".join(parts)


def _spec(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


async def _call_tool(svc, c: Campaign, cfg: AgentConfig, purpose: str, msgs: list, spec: dict, check) -> Any:
    """Вызов модели с одним инструментом и проверкой сервера; ошибки возвращаются модели. Учёт — в llm_calls."""
    from app.agents.architect import model_of

    async with svc.maker() as s:
        _, model, api_base, temperature = await model_of(s, await s.get(Campaign, c.id))
    name = spec["function"]["name"]
    calls, result = [], None
    try:
        for _ in range(ATTEMPTS):
            call = LlmCall(campaign_id=c.id, seat_id=master_seat(c).id, turn_id=None, purpose=purpose, model=model)
            calls.append(call)
            try:
                reply = await svc.llm.complete(
                    msgs, model=model, tools=[spec], max_tokens=2000, temperature=temperature, api_base=api_base
                )
            except LLMError as e:
                call.error = str(e)[:2000]
                break
            call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
            call.cost, call.latency_ms = reply.cost, reply.latency_ms
            tc = next((t for t in reply.tool_calls if t.name == name), None)
            if tc is None:
                call.error = f"модель не вызвала {name}"
                msgs = [*msgs, reply.message or {"role": "assistant", "content": reply.text}]
                msgs.append({"role": "user", "content": f"Ответь вызовом {name}."})
                continue
            value, errors = check(tc.arguments)
            if not errors:
                result = value
                break
            call.error = "; ".join(errors)[:2000]
            from app.agents.architect import _assistant

            msgs = [
                *msgs,
                _assistant(reply, tc),
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({"ok": False, "errors": errors}, ensure_ascii=False),
                },
            ]
    finally:
        async with svc.maker() as s:
            s.add_all(calls)
            await s.commit()
    return result


# --- вопросы о связях ---


async def ask_questions(svc, cid: str, character_id: str) -> bool:
    """ИИ-мастер задаёт герою 2–3 вопроса под завязку и отряд. Сбой оставляет вопросы по умолчанию."""
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        ch = await s.get(Character, character_id)
        if c is None or ch is None or ch.campaign_id != cid:
            return False
        cfg, p = await _ai_plan(s, c)
        if cfg is None:
            return False
        others = (
            await s.scalars(
                select(Character).where(
                    Character.campaign_id == cid, Character.status.in_(PLAYING), Character.id != character_id
                )
            )
        ).all()
        hero = await _hero(s, c, ch, private=True)
        party = "\n".join([await _hero(s, c, o, private=False) for o in others]) or "пока нет"
        excluded = list((c.settings or {}).get("excluded_themes") or [])
    prompt = (
        f"Кампания «{p.get('title')}». Завязка для игроков: {p.get('public_intro')}\n"
        f"Конфликт (тайно, в вопросах не раскрывай): {p.get('conflict')}\n"
        f"Злодеи (тайно): {', '.join(a.get('name', '') for a in p.get('antagonists') or [])}\n\n"
        f"Герой:\n{hero}\n\nДругие герои отряда:\n{party}\n\n"
        "Задай игроку от 2 до 3 коротких вопросов, ответы на которые свяжут героя с завязкой и с другими героями: "
        "«Что у тебя отнял тот, кто стоит за пропажами?», «Кому из отряда ты обязан жизнью?». Вопросы видит игрок: "
        "в них нет тайн каркаса и имён злодеев, которых герои ещё не знают."
        + (f" Запретные темы: {', '.join(excluded)}." if excluded else "")
    )

    def check(args: dict) -> tuple[list[str] | None, list[str]]:
        qs = [str(q).strip() for q in args.get("questions") or [] if str(q).strip()]
        errs = []
        if not bonds.MIN_QUESTIONS <= len(qs) <= bonds.MAX_QUESTIONS:
            errs.append(f"вопросов от {bonds.MIN_QUESTIONS} до {bonds.MAX_QUESTIONS}")
        hits = plot._banned(" ".join(qs), excluded)
        if hits:
            errs.append("запретные темы: " + ", ".join(hits))
        return qs, errs

    spec = _spec(
        QUESTIONS_TOOL,
        "Сдать вопросы о связях героя.",
        {"questions": {"type": "array", "items": {"type": "string", "maxLength": bonds.MAX_QUESTION}}},
        ["questions"],
    )
    msgs = [
        {"role": "system", "content": f"Ты — мастер ролевой игры по D&D 5e на русском языке. {cfg.persona or ''}"},
        {"role": "user", "content": prompt},
    ]
    qs = await _call_tool(svc, c, cfg, "bonds", msgs, spec, check)
    async with svc.maker() as s:
        ch = await s.get(Character, character_id)
        b = bonds.bonds_of(ch)
        if qs is not None and not (b.get("answers") and b.get("source") == "default"):
            bonds.set_questions(ch, qs, "master")  # на вопросы по умолчанию игрок уже ответил — их не трогаем
        b = bonds.bonds_of(ch)
        b["status"] = "ready" if qs is not None else "failed"
        bonds._save(ch, b)
        await s.commit()
        await publish_bonds(svc.bus, await s.get(Campaign, cid), ch)
    return qs is not None


async def publish_bonds(bus, c: Campaign, ch: Character) -> None:
    """Вопросы и ответы уходят только игроку героя и мастеру: в личных ответах могут быть тайны."""
    seats = [x for x in (ch.seat_id, master_seat(c).id) if x]
    payload = {"character_id": ch.id, "bonds": bonds.bonds_of(ch)}
    await bus.publish(c.id, envelope("character.bonds", c.id, payload), seats)


# --- личный крючок ---


async def make_hook(svc, cid: str, character_id: str) -> bool:
    """По ответам о связях ИИ-мастер тайно привязывает героя к узлу, NPC, злодею или месту каркаса."""
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        ch = await s.get(Character, character_id)
        if c is None or ch is None or ch.campaign_id != cid or not bonds.bonds_of(ch).get("answers"):
            return False
        cfg, p = await _ai_plan(s, c)
        if cfg is None:
            return False
        hero = await _hero(s, c, ch, private=True)
    targets = plot.hook_targets(p)
    prompt = (
        f"{plot.render(p)}\n\nГерой:\n{hero}\n\n"
        "Свяжи историю героя с каркасом: выбери узел, NPC, злодея или место, которые ударят по нему лично, и опиши "
        "связь одной-двумя фразами. Это тайна мастера: игрок узнает её в игре. Опирайся на ответы о связях."
    )

    def check(args: dict) -> tuple[dict | None, list[str]]:
        ref, text = str(args.get("ref") or ""), str(args.get("text") or "").strip()
        errs = []
        if ref not in targets:
            errs.append(f"ref: нужен один из {', '.join(targets[:40])}")
        if not text:
            errs.append("нужен текст связи")
        return {"ref": ref, "text": text[:600]}, errs

    spec = _spec(
        HOOK_TOOL,
        "Сдать личный крючок героя.",
        {
            "ref": {"type": "string", "enum": targets} if len(targets) <= 60 else {"type": "string"},
            "text": {"type": "string", "maxLength": 600},
        },
        ["ref", "text"],
    )
    msgs = [
        {"role": "system", "content": "Ты — мастер ролевой игры по D&D 5e на русском языке. Готовишь кампанию."},
        {"role": "user", "content": prompt},
    ]
    hook = await _call_tool(svc, c, cfg, "hook", msgs, spec, check)
    if hook is None:
        return False
    async with svc.maker() as s:
        ch = await s.get(Character, character_id)
        secret = await s.get(CampaignSecret, cid)
        fresh = dict(secret.plot or {})
        try:
            plot.set_hook(fresh, ch.id, ch.name, hook["ref"], hook["text"])
        except plot.PlotError:
            return False  # пока модель думала, узел закрылся: крючок не нужен
        fresh.setdefault("character_links", {})[ch.id] = hook["text"]
        secret.plot = json.loads(json.dumps(fresh))  # новый объект, чтобы JSON-поле точно записалось
        await s.commit()
    return True


# --- вступление ---


def _introduced(scene: Scene | None) -> list[str]:
    return list(((scene.state if scene else None) or {}).get("introduced") or [])


async def pending(s, c: Campaign) -> list[Character]:
    """Герои за столом, которых мастер ещё не представил."""
    scene = await s.get(Scene, c.id)
    done = set(_introduced(scene))
    rows = await s.scalars(
        select(Character)
        .where(Character.campaign_id == c.id, Character.status.in_(PLAYING), Character.seat_id.is_not(None))
        .order_by(Character.created_at)
    )
    return [ch for ch in rows if ch.id not in done]


async def _open_first_place(svc, cid: str, where: dict) -> None:
    """Место первой сцены попадает в мир до вступления: у него появляется карточка, и имя в тексте становится
    ссылкой. Детали и тайна места остаются в каркасе, в карточку идёт только настроение («mood»)."""
    from app.tools.registry import execute
    from app.tools.runtime import flush_outbox, open_context, publish_changes

    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, svc.dice_factory(), turn_id=None, seat_id=master_seat(c).id)
        details = where.get("mood") or where.get("name") or "место первой сцены"
        result = await execute(ctx, "develop", {"sketch_id": where["id"], "details": details, "here": True})
        if not result.get("ok"):
            log.warning("место первой сцены не открылось: %s", result.get("error"))
            await s.rollback()
            return
        messages = await flush_outbox(s, ctx)
        await s.commit()
    await publish_changes(svc.bus, ctx, messages)


async def introduce_campaign(svc, cid: str) -> str | None:
    """Глобальное вступление ко всей кампании (2–4 абзаца): обстановка в мире, где и почему
    оказались герои, непосредственное окружение. Запускается один раз при старте первой сессии со стримингом."""
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        if c is None or (c.settings or {}).get("campaign_intro_played"):
            return None
        cfg, p = await _ai_plan(s, c)
        game = await active_session(s, cid)
        if cfg is None or game is None:
            return None
        seat_id = master_seat(c).id

    act = plot.active_act(p) or {}
    node = next((n for n in act.get("nodes") or [] if n.get("status") not in plot.CLOSED), None)
    where = next((x for x in p.get("locations") or [] if node and x["id"] == node.get("location_id")), None)
    if where and not where.get("entity_id"):
        try:
            await _open_first_place(svc, cid, where)
        except Exception:
            log.exception("не удалось открыть первое место до интро кампании")

    scene_hint = ""
    if node:
        scene_hint = (
            f"Первая сцена (тайно, покажи только то, что видят герои): {node.get('title')} — {node.get('summary')}"
        )
        if where:
            scene_hint += f" Место: {where.get('name')}, {where.get('mood')}"

    task = (
        "Напиши масштабное и атмосферное художественное вступление к всей кампании (2–4 абзаца). "
        "Опиши общую ситуацию в мире и регионе, где именно сейчас оказались герои и почему/при каких "
        "обстоятельствах они здесь очутились, передай живую атмосферу и настроение места. "
        "Не управляй действиями и репликами персонажей игроков. Закончи описанием того, что герои видят прямо перед собой."
    )
    user = "\n\n".join(
        x
        for x in (
            f"Кампания «{p.get('title') or c.name}». Завязка: {p.get('public_intro') or c.public_intro}",
            scene_hint,
            task,
        )
        if x
    )
    msgs = [
        {
            "role": "system",
            "content": f"Ты — мастер ролевой игры «{p.get('title') or c.name}» по D&D 5e на русском языке. {cfg.persona or ''}",
        },
        {"role": "user", "content": user},
    ]

    from app.agents.architect import model_of

    async with svc.maker() as s:
        _, model, api_base, temperature = await model_of(s, await s.get(Campaign, cid))
        game = await active_session(s, cid)
        msg = Message(
            campaign_id=cid,
            session_id=game.id if game else None,
            seq=await next_seq(s, cid),
            seat_id=seat_id,
            kind="narration",
            content="",
        )
        s.add(msg)
        await s.flush()
        msg_id = msg.id
        await s.commit()

    await publish_message(svc.bus, msg)

    async def stream_chunk(chunk: str):
        await svc.bus.publish(cid, envelope("message.chunk", cid, {"id": msg_id, "chunk": chunk}), None)

    call = LlmCall(campaign_id=cid, seat_id=seat_id, turn_id=None, purpose="campaign_intro", model=model)
    text = ""
    try:
        reply = await svc.llm.complete(
            msgs,
            model=model,
            tools=None,
            max_tokens=1500,
            temperature=temperature,
            api_base=api_base,
            stream_callback=stream_chunk,
        )
        call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
        call.cost, call.latency_ms = reply.cost, reply.latency_ms
        text = reply.text.strip()
    except LLMError as e:
        call.error = str(e)[:2000]

    async with svc.maker() as s:
        s.add(call)
        c = await s.get(Campaign, cid)
        msg_db = await s.get(Message, msg_id)
        if text and msg_db:
            msg_db.content = await link_text(s, cid, text)
            if c:
                c.settings = {**(c.settings or {}), "campaign_intro_played": True}
            await s.commit()
            return msg_id
        else:
            if msg_db:
                await s.delete(msg_db)
            await s.commit()
            await svc.bus.publish(cid, envelope("message.withdrawn", cid, {"id": msg_id}), None)
            return None


async def introduce(svc, cid: str) -> str | None:
    """Вступление: как герои встретились (120–200 слов) или, если отряд уже в игре, короткое появление новичков.
    Транслируется со стримингом. Возвращает id сообщения или None."""
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        if c is None:
            return None
        cfg, p = await _ai_plan(s, c)
        game = await active_session(s, cid)
        if cfg is None or game is None:
            return None
        newcomers = await pending(s, c)
        if not newcomers:
            return None
        scene = await s.get(Scene, cid)
        first = not _introduced(scene)
        heroes = "\n\n".join([await _hero(s, c, ch, private=False) for ch in newcomers])
        hooks = (p.get("hooks") or {}) if p else {}
        hints = "\n".join(f"- {ch.name}: {hooks[ch.id]['text']}" for ch in newcomers if ch.id in hooks)
        seat_id = master_seat(c).id
    act = plot.active_act(p) or {}
    node = next((n for n in act.get("nodes") or [] if n.get("status") not in plot.CLOSED), None)
    where = next((x for x in p.get("locations") or [] if node and x["id"] == node.get("location_id")), None)
    if first and where and not where.get("entity_id"):
        try:
            await _open_first_place(svc, cid, where)
        except Exception:
            log.exception("не удалось открыть первое место до вступления героев")
    scene_hint = ""
    if node:
        scene_hint = (
            f"Первая сцена (тайно, покажи только то, что видят герои): {node.get('title')} — {node.get('summary')}"
        )
        if where:
            scene_hint += f" Место: {where.get('name')}, {where.get('mood')}"
    if first:
        task = (
            "Напиши вступление кампании: как эти герои встретились. 120–200 слов. У каждого героя — одна яркая деталь "
            "из его класса, происхождения, характера или ответов о связях. Общий повод сводит их вместе, затем "
            "переход прямо в первую сцену. Коротко и харизматично."
        )
    else:
        task = (
            "Отряд уже в игре. Напиши короткое появление нового героя (или героев): 50–100 слов, одна яркая деталь "
            "и повод присоединиться к отряду прямо сейчас."
        )
    user = "\n\n".join(
        x
        for x in (
            f"Кампания «{p.get('title')}». Завязка для игроков: {p.get('public_intro')}",
            scene_hint,
            "Герои:\n" + heroes,
            ("Личные крючки (тайно, не раскрывай, можно намекнуть):\n" + hints) if hints else "",
            task
            + " Имена героев размечай как [[id|Имя]], других разметок не добавляй. Не решай за игроков, что делают "
            "их герои дальше, закончи тем, что они видят.",
        )
        if x
    )
    msgs = [
        {
            "role": "system",
            "content": f"Ты — мастер ролевой игры «{p.get('title')}» по D&D 5e на русском языке. {cfg.persona or ''}",
        },
        {"role": "user", "content": user},
    ]
    from app.agents.architect import model_of

    async with svc.maker() as s:
        _, model, api_base, temperature = await model_of(s, await s.get(Campaign, cid))
        game = await active_session(s, cid)
        msg = Message(
            campaign_id=cid,
            session_id=game.id if game else None,
            seq=await next_seq(s, cid),
            seat_id=seat_id,
            kind="narration",
            content="",
        )
        s.add(msg)
        await s.flush()
        msg_id = msg.id
        await s.commit()

    await publish_message(svc.bus, msg)

    async def stream_chunk(chunk: str):
        await svc.bus.publish(cid, envelope("message.chunk", cid, {"id": msg_id, "chunk": chunk}), None)

    call = LlmCall(campaign_id=cid, seat_id=seat_id, turn_id=None, purpose="intro", model=model)
    text = ""
    try:
        reply = await svc.llm.complete(
            msgs,
            model=model,
            tools=None,
            max_tokens=1200,
            temperature=temperature,
            api_base=api_base,
            stream_callback=stream_chunk,
        )
        call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
        call.cost, call.latency_ms = reply.cost, reply.latency_ms
        known = {ch.id for ch in newcomers}
        text = MARKUP.sub(lambda m: m.group(0) if m.group(1) in known else m.group(2), reply.text.strip())
    except LLMError as e:
        call.error = str(e)[:2000]

    async with svc.maker() as s:
        s.add(call)
        c = await s.get(Campaign, cid)
        scene = await s.get(Scene, cid)
        msg_db = await s.get(Message, msg_id)
        if text and msg_db:
            msg_db.content = await link_text(s, cid, text)
            # представленными считаем только после удачного вступления: при сбое мастер попробует на следующем ходу
            if scene:
                scene.state = {**(scene.state or {}), "introduced": _introduced(scene) + [ch.id for ch in newcomers]}
            await s.commit()
            return msg_id
        else:
            if msg_db:
                await s.delete(msg_db)
            await s.commit()
            await svc.bus.publish(cid, envelope("message.withdrawn", cid, {"id": msg_id}), None)
            return None
