"""Перед игрой (проект «Подготовка кампании», разделы 5 и 7.1): вопросы о связях героев, личные крючки и вступление.

Всё это делает ИИ-мастер на своей модели и только когда у кампании есть каркас: вопросы и вступление опираются
на завязку и первый узел. У живого мастера герои получают вопросы по умолчанию, а вступление он пишет сам.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from sqlalchemy import select

from app.agents import textcalls, voiceover, voicing
from app.agents.llm import LLMError
from app.content.catalog import campaign_catalog
from app.core import adventure, bonds, plot
from app.core.campaigns import master_seat
from app.core.chat import active_session, next_seq
from app.core.linker import link_text
from app.core.llm_diagnostics import reply_metrics
from app.db.models import AgentConfig, Campaign, CampaignSecret, Character, LlmCall, Message, Scene
from app.gateway.events import Stream, envelope, publish_message

log = logging.getLogger(__name__)

ATTEMPTS = 2
QUESTIONS_TOOL = "submit_bond_questions"
HOOK_TOOL = "submit_hook"
PLAYING = ("approved", "active")
MARKUP = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")
# служебные строки, которые модель иногда ставит перед текстом: заголовок, «Вступление:», повтор задания
HEADING = re.compile(r"^\s*(#.*|[*_]{1,3}[^\n]{1,150}?[*_]{1,3}:?|[^\n]{0,150}:|[^\n.!?…»]{1,60})\s*$")
ECHO = re.compile(r"^\s*Кампания\s+«[^»\n]*»\.?\s*(Завязка[^:\n]*:\s*)?")
STORY_RULES = (
    "Сразу начни сам художественный текст: без заголовка, пояснений и вводных фраз вроде «Вот вступление», "
    "не повторяй название кампании и слова задания. Не утверждай о наличии снаряжения вопреки фактическому "
    "листу персонажа."
)


def clean_story(text: str, keep=lambda _id: False) -> str:
    """Текст повествования для игроков: без чужой разметки, служебного заголовка и повтора завязки из подсказки.
    Строка в начале считается заголовком, только если за ней есть текст: в потоке первая строка ещё пишется."""
    text = MARKUP.sub(lambda m: m.group(0) if keep(m.group(1)) else m.group(2), text.strip())
    text = textcalls.clean(text)  # вызовы инструментов, написанные текстом, игрокам не показываем
    lines = text.split("\n")
    while len(lines) > 1 and (not lines[0].strip() or HEADING.match(lines[0])):
        lines.pop(0)
    return ECHO.sub("", "\n".join(lines).strip(), count=1).strip()


def _closed(raw: str) -> str:
    """Текст без недописанной разметки в конце: «[[en_1|гобл» станет словом, только когда закроется, иначе
    черновик пришлось бы стирать и печатать заново."""
    i = raw.rfind("[[")
    return raw[:i] if i >= 0 and "]]" not in raw[i:] else raw


class StoryFeed:
    """Поток повествования в чат и в озвучку уже очищенным: служебный заголовок модели игроки не видят и в
    черновике. Первая строка ждёт, пока допишется (по ней видно, заголовок ли это)."""

    def __init__(self, stream: Stream | None, job: voiceover.VoiceJob | None, clean=clean_story) -> None:
        self.stream, self.job, self.clean = stream, job, clean
        self.raw, self.sent, self.voiced = "", "", ""

    async def push(self, chunk: str) -> None:
        self.raw += chunk
        safe_raw = textcalls.stream_prefix(self.raw)
        if self.job is not None:
            # Do not feed a partial JSON key to speech synthesis; its identity
            # is only known after more chunks arrive.
            self.job.feed(safe_raw[len(self.voiced) :])
            self.voiced = safe_raw
        if self.stream is None or ("\n" not in self.raw and len(self.raw) < 200):
            return
        view = self.clean(_closed(safe_raw))
        if view.startswith(self.sent):
            if len(view) > len(self.sent):
                await self.stream.push(view[len(self.sent) :])
        else:
            await self.stream.reset()
            await self.stream.push(view)
        self.sent = view


def _intro_voice(svc, c: Campaign):
    """Озвучка подготовки к игре — всегда облако (app/agents/voicing.py); None — выключена или облако не подключено."""
    tts_for = getattr(svc, "_tts_for", None)
    return tts_for(c, voicing.INTRO) if tts_for is not None else None


def _spawn(svc, coro) -> None:
    """Досинтез частей идёт в фоне: игра не ждёт голос, текст уже в чате."""
    spawn = getattr(svc, "_spawn", None)
    if spawn is not None:
        spawn(coro)
    else:
        asyncio.get_running_loop().create_task(coro)


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
            for metric, value in reply_metrics(reply).items():
                setattr(call, metric, value)
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


async def _opening_npcs(ctx, node, fresh_where, where) -> bool:
    from app.tools.registry import execute

    if not (node and fresh_where and fresh_where["id"] == where["id"]):
        return True
    for npc in ctx.world.plot.get("npcs") or []:
        if npc["id"] not in (node.get("npc_ids") or []):
            continue
        if npc.get("location_id") not in (None, where["id"]):
            continue
        if npc.get("entity_id") in ctx.world.entities:
            continue
        result = await execute(
            ctx,
            "develop",
            {
                "sketch_id": npc["id"],
                "details": npc.get("look") or npc["name"],
                "here": True,
                "attitude": "neutral",
                "location_id": ctx.world.scene.location_id,
            },
        )
        if not result.get("ok"):
            log.warning("NPC первой сцены не появился: %s", result.get("error"))
            return False
    return True


async def _open_first_place(svc, cid: str, where: dict) -> bool:
    """Место первой сцены попадает в мир до вступления: у него появляется карточка, и имя в тексте становится
    ссылкой. Детали и тайна места остаются в каркасе, в карточку идёт только настроение («mood»)."""
    from app.tools.registry import execute
    from app.tools.runtime import flush_outbox, open_context, publish_changes

    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, svc.dice_factory(), turn_id=None, seat_id=master_seat(c).id)
        # Read fresh plot state: campaign and hero introductions both prepare
        # this scene, and callers may hold a stale copy of the opening sketch.
        node, fresh_where = _first_scene(ctx.world.plot)
        where = next((x for x in ctx.world.plot.get("locations") or [] if x["id"] == where["id"]), where)
        place = ctx.world.entities.get(where.get("entity_id") or "")
        created = place is None
        if created:
            details = where.get("mood") or where.get("name") or "место первой сцены"
            result = await execute(ctx, "develop", {"sketch_id": where["id"], "details": details, "here": True})
            if not result.get("ok"):
                log.warning("место первой сцены не открылось: %s", result.get("error"))
                await s.rollback()
                return False
            place = ctx.world.entities.get((result.get("result") or {}).get("entity_id") or "")
        # готовое приключение: отряд начинает в первой комнате книги, иначе героя нет на её карте, пока мастер
        # не вспомнит про enter_room
        found = adventure.module_place(place, ctx.world.catalog, ctx.world.entities)
        if found is not None and created:
            first = adventure.rooms(found[1])[0]
            entered = await execute(ctx, "enter_room", {"room": str(first.get("number") or first["id"])})
            if not entered.get("ok"):
                log.warning("отряд не вошёл в первую комнату приключения: %s", entered.get("error"))
                await s.rollback()
                return False
        # Only NPCs explicitly participating in the first node are visible at
        # the opening. Other inhabitants and antagonists remain undisclosed.
        from app.core.world_generation import storage

        layout = await storage.find(s, cid, place.id, "location_layout")
        deferred = layout is not None  # комплекс: участники узла встанут рядом с героями уже внутри
        if not deferred and not await _opening_npcs(ctx, node, fresh_where, where):
            await s.rollback()
            return False
        messages = await flush_outbox(s, ctx)
        await s.commit()
    await publish_changes(svc.bus, ctx, messages)
    if ctx.operation_refs:
        await svc._settle_preparation(cid, list(ctx.operation_refs))
    if deferred:
        from app.core.layout import entry

        await entry.enter_complex(svc.maker, svc.preparer, svc.dice_factory, cid, place.id, bus=svc.bus)
        async with svc.maker() as s:
            c = await s.get(Campaign, cid)
            ctx = await open_context(s, c, svc.dice_factory(), turn_id=None, seat_id=master_seat(c).id)
            node, fresh_where = _first_scene(ctx.world.plot)
            if not await _opening_npcs(ctx, node, fresh_where, where):
                await s.rollback()
                return False
            messages = await flush_outbox(s, ctx)
            await s.commit()
        await publish_changes(svc.bus, ctx, messages)
        if ctx.operation_refs:
            await svc._settle_preparation(cid, list(ctx.operation_refs))
    return True


async def _apply_opening_conditions(
    svc,
    cid: str,
    p: dict,
    newcomers: list[Character],
    first: bool,
) -> bool:
    """Применяет стартовые условия кампании (изъятие снаряжения) до вступления героев."""
    from app.core.world_objects import read_world_object
    from app.tools.master.items import confiscate_hero_gear, create_stash_container
    from app.tools.registry import execute
    from app.tools.runtime import flush_outbox, open_context, publish_changes

    opening = (p or {}).get("opening") or {}
    if opening.get("gear") != "confiscated":
        return True
    stash_id = opening.get("stash")
    if not stash_id:
        return True

    applied = list(opening.get("applied_to") or [])
    heroes_to_confiscate = [ch for ch in newcomers if ch.id not in applied]
    if not heroes_to_confiscate:
        return True

    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, svc.dice_factory(), turn_id=None, seat_id=master_seat(c).id)
        plot_data = ctx.world.plot or {}
        fresh_opening = dict(plot_data.get("opening") or opening)
        fresh_applied = list(fresh_opening.get("applied_to") or [])
        targets = [ch for ch in heroes_to_confiscate if ch.id not in fresh_applied]
        if not targets:
            return True

        stash_sketch = next((loc for loc in (plot_data.get("locations") or []) if loc["id"] == stash_id), None)
        if stash_sketch is None:
            log.warning("место stash %s не найдено в каркасе", stash_id)
            return False

        stash_place = ctx.world.entities.get(stash_sketch.get("entity_id") or "")
        if stash_place is None:
            details = stash_sketch.get("mood") or stash_sketch.get("name") or "место для изъятых вещей"
            res = await execute(ctx, "develop", {"sketch_id": stash_id, "details": details, "here": False})
            if not res.get("ok"):
                log.warning("не удалось развернуть место stash %s: %s", stash_id, res.get("error"))
                await s.rollback()
                return False
            stash_place_id = (res.get("result") or {}).get("entity_id")
            stash_place = ctx.world.entities.get(stash_place_id or "")
            if stash_place is None:
                log.warning("сущность места stash %s не найдена после develop", stash_id)
                await s.rollback()
                return False
        else:
            stash_place_id = stash_place.id

        containers = [
            e
            for e in ctx.world.in_scene_entities(stash_place_id)
            if read_world_object(e).role == "container" and e.name == "Изъятые вещи"
        ]
        if containers:
            container = containers[0]
        else:
            container = await create_stash_container(ctx, stash_place_id)

        is_opened = bool(read_world_object(container).metadata.get("access", {}).get("open"))
        if not first and is_opened:
            for ch in targets:
                if ch.id not in fresh_applied:
                    fresh_applied.append(ch.id)
        else:
            for ch in targets:
                hero = ctx.world.characters.get(ch.id) or ch
                await confiscate_hero_gear(ctx, hero, container, stash_place_id)
                if ch.id not in fresh_applied:
                    fresh_applied.append(ch.id)

        fresh_opening["applied_to"] = fresh_applied
        plot_data["opening"] = fresh_opening
        secret = await s.get(CampaignSecret, cid)
        if secret is not None:
            fresh_secret = dict(secret.plot or {})
            fresh_secret["opening"] = fresh_opening
            secret.plot = json.loads(json.dumps(fresh_secret))

        messages = await flush_outbox(s, ctx)
        await s.commit()

    await publish_changes(svc.bus, ctx, messages)
    if ctx.operation_refs:
        await svc._settle_preparation(cid, list(ctx.operation_refs))
    return True


INTRO_KEY = "campaign_intro"  # в тайнах кампании: готовое вступление {text, voices, version} до старта
INTRO_TASK = (
    "Напиши художественное вступление ко всей кампании (2–4 абзаца), масштабное и атмосферное. "
    "Опиши общую ситуацию в мире и регионе, где именно сейчас оказались герои и почему/при каких "
    "обстоятельствах они здесь очутились, передай живую атмосферу и настроение места. Завязку перескажи "
    "своими словами, целиком и связно. Не управляй действиями и репликами персонажей игроков. "
    "Закончи описанием того, что герои видят прямо перед собой. " + STORY_RULES
)


def _first_scene(p: dict) -> tuple[dict | None, dict | None]:
    act = plot.active_act(p) or {}
    node = next((n for n in act.get("nodes") or [] if n.get("status") not in plot.CLOSED), None)
    where = next((x for x in p.get("locations") or [] if node and x["id"] == node.get("location_id")), None)
    return node, where


def intro_messages(title: str, public_intro: str, persona: str | None, p: dict) -> list[dict]:
    """Запрос вступления ко всей кампании. Героев в нём нет: о них — знакомство отряда при старте (introduce)."""
    node, where = _first_scene(p)
    scene_hint = ""
    if node:
        scene_hint = (
            f"Первая сцена (тайно, покажи только то, что видят герои): {node.get('title')} — {node.get('summary')}"
        )
        if where:
            scene_hint += f" Место: {where.get('name')}, {where.get('mood')}"
            scene_hint += (
                " Герои начинают именно здесь. Не заменяй это место таверной или другой локацией. "
                "NPC первой сцены перечислены в её каркасе; не добавляй других участников."
            )
    intro = f"Кампания «{title}». Завязка: {public_intro}"
    system = f"Ты — мастер ролевой игры «{title}» по D&D 5e на русском языке. {persona or ''}"
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": "\n\n".join(x for x in (intro, adventure.hook_line(p), scene_hint, INTRO_TASK) if x),
        },
    ]


def _intro_messages(c: Campaign, cfg: AgentConfig, p: dict) -> list[dict]:
    return intro_messages(p.get("title") or c.name, p.get("public_intro") or c.public_intro, cfg.persona, p)


async def write_intro(
    svc,
    msgs: list[dict],
    call: LlmCall,
    api_base: str | None,
    temperature: float,
    stream: Stream | None = None,
    job: voiceover.VoiceJob | None = None,
) -> str:
    """Текст вступления на основной модели без скрытых рассуждений (они съедают лимит и обрывают текст);
    вызов пишется в расходы. Куски потока идут в чат и в озвучку. Пустая строка — модель не ответила."""
    feed = StoryFeed(stream, job)
    text = ""
    try:
        reply = await svc.llm.complete(
            msgs,
            model=call.model,
            tools=None,
            max_tokens=4000,
            temperature=temperature,
            api_base=api_base,
            stream_callback=feed.push if stream is not None or job is not None else None,
            thinking=False,
        )
        call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
        for metric, value in reply_metrics(reply).items():
            setattr(call, metric, value)
        call.cost, call.latency_ms = reply.cost, reply.latency_ms
        text = clean_story(reply.text)  # во вступлении ещё нет сущностей: разметку снимаем
    except LLMError as e:
        call.error = str(e)[:2000]
    async with svc.maker() as s:
        s.add(call)
        await s.commit()
    return text


async def _intro_text(
    svc,
    c: Campaign,
    cfg: AgentConfig,
    p: dict,
    seat_id: str,
    stream: Stream | None = None,
    job: voiceover.VoiceJob | None = None,
) -> str:
    from app.agents.architect import model_of

    async with svc.maker() as s:
        _, model, api_base, temperature = await model_of(s, await s.get(Campaign, c.id))
    call = LlmCall(campaign_id=c.id, seat_id=seat_id, turn_id=None, purpose="campaign_intro", model=model)
    return await write_intro(svc, _intro_messages(c, cfg, p), call, api_base, temperature, stream, job)


def _voice_job(svc, c: Campaign, clean=clean_story) -> voiceover.VoiceJob | None:
    """Озвучка подготовки к игре по частям облачным голосом кампании. Без озвучки — None."""
    ch = _intro_voice(svc, c)
    if ch is None:
        return None

    async def synth(part: str) -> dict | None:
        return await svc.tts.voice_for_narration(svc.media_dir, c.id, part, provider=ch.provider, voice_name=ch.voice)

    return voiceover.VoiceJob(synth, clean)


def _module_of(svc, c: Campaign) -> str | None:
    mod = (c.settings or {}).get("module") or {}
    return mod.get("id") if mod.get("id") and getattr(svc, "media_dir", None) else None


def _saved_module_intro(svc, c: Campaign, p: dict) -> dict | None:
    """Сохранённое админом вступление готового приключения для зацепки кампании (app/agents/module_intro.py)."""
    from app.agents import module_intro

    mid = _module_of(svc, c)
    return module_intro.saved_for(svc.media_dir, mid, module_intro.hook_of(p)) if mid else None


def _module_voices(svc, c: Campaign, entry: dict) -> list[dict] | None:
    """Записи сохранённого вступления в папку кампании, если голос кампании тот же; None — голос другой
    (или записей нет), и текст озвучивается голосом кампании."""
    from app.agents import module_intro

    ch = _intro_voice(svc, c)
    if ch is None:
        return []
    mine = module_intro.voice_of(svc, ch.provider, ch.voice)
    theirs = module_intro.voice_of(svc, entry.get("provider"), entry.get("voice"))
    if mine != theirs or not entry.get("voices"):
        return None
    voices = module_intro.copy_voices(svc.media_dir, _module_of(svc, c), c.id, entry["voices"])
    return voices if len(voices) == len(entry["voices"]) else None


async def prepare_campaign_intro(svc, cid: str) -> bool:
    # Background preparation and session startup share the same lock; starting
    # while the background model is running must reuse its completed intro.
    async with svc.intro_lock(cid):
        return await _prepare_campaign_intro(svc, cid)


async def _prepare_campaign_intro(svc, cid: str) -> bool:
    """Готовит вступление ко всей кампании один раз, когда каркас готов: текст и голос ждут старта в тайнах,
    и игрокам не приходится ждать модель на первом ходу. Новый вариант каркаса готовит вступление заново."""
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        if c is None or (c.settings or {}).get("campaign_intro_played"):
            return False
        cfg, p = await _ai_plan(s, c)
        if cfg is None:
            return False
        secret = await s.get(CampaignSecret, cid)
        ready = ((secret.setting if secret else None) or {}).get(INTRO_KEY) or {}
        if ready.get("text") and ready.get("version") == p.get("version"):
            return False
        seat_id = master_seat(c).id
    saved = _saved_module_intro(svc, c, p)
    if saved:  # готовое приключение: вступление, проверенное админом, одно на все кампании
        text = saved["text"]
        voices = _module_voices(svc, c, saved)
        if voices is None:
            job = _voice_job(svc, c)
            voices = [v for v in await asyncio.gather(*job.finish(text)) if v] if job is not None else []
    else:
        job = _voice_job(svc, c)
        text = await _intro_text(svc, c, cfg, p, seat_id, job=job)
        if not text:
            if job is not None:
                job.cancel()
            return False
        voices = [v for v in await asyncio.gather(*job.finish(text)) if v] if job is not None else []
    async with svc.maker() as s:
        secret = await s.get(CampaignSecret, cid)
        if secret is None:
            return False
        ready = {"text": text, "voices": voices, "version": p.get("version")}
        secret.setting = {**(secret.setting or {}), INTRO_KEY: ready}
        await s.commit()
    return True


GREETING_TASK = (
    "Поприветствуй игроков за столом от первого лица, как живой мастер перед первой игрой: тепло и с "
    "предвкушением, 40–80 слов. Назови приключение, обратись к героям по именам, пообещай интересное и скажи, "
    "что начинаем. Это слова мастера игрокам, а не повествование: сюжет и завязку не раскрывай. "
    "Не описывай место героев, появление NPC, их диалоги и события мира: всё это будет во вступлении. " + STORY_RULES
)


async def greet(svc, cid: str) -> str | None:
    """Приветствие мастера перед первой игрой кампании: отдельное голосовое сообщение до вступления.
    Пишется при старте сессии (знает героев за столом), один раз на кампанию, озвучивается по частям."""
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        st = (c.settings or {}) if c else {}
        if c is None or st.get("campaign_intro_played") or st.get("master_greeted"):
            return None
        cfg, p = await _ai_plan(s, c)
        game = await active_session(s, cid)
        if cfg is None or game is None:
            return None
        heroes = [await _hero(s, c, ch, private=False) for ch in await pending(s, c)]
        seat_id = master_seat(c).id
        from app.agents.architect import model_of

        _, model, api_base, temperature = await model_of(s, c)
    title = p.get("title") or c.name
    user = "\n\n".join(
        x
        for x in (
            f"Приключение «{title}».",
            ("Герои за столом:\n" + "\n\n".join(heroes)) if heroes else "",
            GREETING_TASK + " Разметку [[...]] не используй.",
        )
        if x
    )
    msgs = [
        {
            "role": "system",
            "content": f"Ты — мастер ролевой игры «{title}» по D&D 5e на русском языке. {cfg.persona or ''}",
        },
        {"role": "user", "content": user},
    ]
    await _set_flag(svc, cid, True)  # реплики ждут вводной: снимет вступление кампании или конец старта сессии
    call = LlmCall(campaign_id=cid, seat_id=seat_id, turn_id=None, purpose="greeting", model=model)
    job = _voice_job(svc, c)
    text = await write_intro(svc, msgs, call, api_base, temperature, job=job)
    tasks = job.finish(text) if job is not None and text else []
    if job is not None and not tasks:
        job.cancel()
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        c.settings = {**(c.settings or {}), "master_greeted": True}  # и при сбое: игра не ждёт приветствия
        if not text:
            await s.commit()
            return None
        msg = Message(
            campaign_id=cid,
            session_id=game.id,
            seq=await next_seq(s, cid),
            seat_id=seat_id,
            kind="narration",
            content=text,
            data={"greeting": True, **(voiceover.data_of([], len(tasks)) if tasks else {})},
        )
        s.add(msg)
        await s.commit()
        await publish_message(svc.bus, msg)
    if tasks:
        _spawn(svc, voiceover.attach(svc, msg, tasks))
    return msg.id


async def _set_flag(svc, cid: str, on: bool) -> None:
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        if c is not None:
            c.settings = {**(c.settings or {}), "intro_generating": on}
            await s.commit()


async def introduce_campaign(svc, cid: str) -> str | None:
    """Вступление ко всей кампании при старте первой сессии, одно на кампанию, у всех игроков сразу.
    Берёт заготовленное (prepare_campaign_intro); если его нет — пишет сейчас со стримингом, а игроки ждут:
    реплики до конца вступления сервер отклоняет с причиной."""
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        if c is None or (c.settings or {}).get("campaign_intro_played"):
            return None
        cfg, p = await _ai_plan(s, c)
        game = await active_session(s, cid)
        if cfg is None or game is None:
            return None
        seat_id = master_seat(c).id
        secret = await s.get(CampaignSecret, cid)
        ready = ((secret.setting if secret else None) or {}).get(INTRO_KEY) or {}
        if ready.get("version") != p.get("version"):
            ready = {}  # заготовка к старому варианту каркаса
        # без rollback: закрытая сессия оставляет загруженные поля кампании и сессии читаемыми

    await _set_flag(svc, cid, True)
    try:
        _, where = _first_scene(p)
        if where:
            try:
                if not await _open_first_place(svc, cid, where):
                    return None
            except Exception:
                log.exception("не удалось открыть первое место до вступления кампании")
                return None

        async with svc.maker() as s:
            msg = Message(
                campaign_id=cid,
                session_id=game.id,
                seq=await next_seq(s, cid),
                seat_id=seat_id,
                kind="narration",
                content="",
            )
            s.add(msg)
            await s.commit()
            msg_id = msg.id
        text = ready.get("text") or ""
        voices = ready.get("voices") or ([ready["voice"]] if ready.get("voice") else [])
        tasks: list[asyncio.Task] = []
        saved = _saved_module_intro(svc, c, p)
        if saved and saved["text"] != text:  # админ сохранил вступление приключения позже заготовки кампании
            text = saved["text"]
            voices = _module_voices(svc, c, saved)
            if voices is None:
                voices, job = [], _voice_job(svc, c)
                tasks = job.finish(text) if job is not None else []
        if not text:
            job = _voice_job(svc, c)  # части озвучиваются, пока модель ещё пишет: первая готова раньше всех
            text = await _intro_text(svc, c, cfg, p, seat_id, stream=Stream(svc.bus, cid, msg), job=job)
            if job is not None:
                tasks = job.finish(text) if text else []
                if not text:
                    job.cancel()

        async with svc.maker() as s:
            msg = await s.get(Message, msg_id)
            if not text:
                await s.delete(msg)
                await s.commit()
                await svc.bus.publish(cid, envelope("message.withdrawn", cid, {"id": msg_id}), None)
                return None
            msg.content = await link_text(s, cid, text)
            if voices or tasks:
                msg.data = voiceover.data_of(voices, len(voices) or len(tasks))
            c = await s.get(Campaign, cid)
            c.settings = {**(c.settings or {}), "campaign_intro_played": True}
            secret = await s.get(CampaignSecret, cid)
            if secret is not None and INTRO_KEY in (secret.setting or {}):
                secret.setting = {k: v for k, v in secret.setting.items() if k != INTRO_KEY}
            await s.commit()
            await publish_message(svc.bus, msg)
        if tasks:
            _spawn(svc, voiceover.attach(svc, msg, tasks))
        return msg_id
    finally:
        await _set_flag(svc, cid, False)


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
    if first and where:
        try:
            if not await _open_first_place(svc, cid, where):
                return None
        except Exception:
            log.exception("не удалось открыть первое место до вступления героев")
            return None
    try:
        if not await _apply_opening_conditions(svc, cid, p, newcomers, first):
            return None
    except Exception:
        log.exception("не удалось применить стартовые условия кампании")
        return None
    from app.tools.runtime import open_context

    async with svc.maker() as s:
        current = await s.get(Campaign, cid)
        ctx = await open_context(s, current, svc.dice_factory(), turn_id=None, seat_id=seat_id)
        factual_scene = ctx.world.scene_table()
        previous = list(
            await s.scalars(
                select(Message)
                .where(
                    Message.campaign_id == cid,
                    Message.kind == "narration",
                    Message.visible_to.is_(None),
                    Message.content != "",
                )
                .order_by(Message.seq.desc())
                .limit(3)
            )
        )
        previous_text = "\n".join(clean_story(m.content) for m in reversed(previous))[-8000:]
    scene_hint = ""
    if first and node:
        scene_hint = (
            f"Первая сцена (тайно, покажи только то, что видят герои): {node.get('title')} — {node.get('summary')}"
        )
        if where:
            scene_hint += f" Место: {where.get('name')}, {where.get('mood')}"
    opening = (p or {}).get("opening") or {}
    opening_note = ""
    if opening.get("gear") == "confiscated":
        stash_id = opening.get("stash")
        stash_sketch = next((loc for loc in (p.get("locations") or []) if loc["id"] == stash_id), None)
        stash_name = stash_sketch.get("name") if stash_sketch else stash_id
        note_extra = f" ({opening['note']})" if opening.get("note") else ""
        opening_note = (
            f"Стартовое условие кампании: снаряжение героев изъято и находится в месте «{stash_name}»{note_extra}. "
            "Не описывай наличие оружия, доспехов или снаряжения вопреки фактическому листу персонажа."
        )
    if first:
        task = (
            "Напиши, как эти герои встретились. 120–200 слов. У каждого героя — одна яркая деталь "
            "из его класса, происхождения, характера или ответов о связях. Общий повод сводит их вместе, затем "
            "переход прямо в первую сцену. Коротко и харизматично. Общее вступление к кампании игроки уже "
            "слышали: завязку не пересказывай."
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
            adventure.hook_line(p) if first else "",
            opening_note,
            scene_hint,
            "Фактическая сцена (достовернее завязки и прошлых описаний):\n" + factual_scene,
            "Уже рассказано игрокам:\n" + previous_text if previous_text else "",
            "Герои:\n" + heroes,
            ("Личные крючки (тайно, не раскрывай, можно намекнуть):\n" + hints) if hints else "",
            task
            + " Имена героев размечай как [[id|Имя]], других разметок не добавляй. Не решай за игроков, что делают "
            "их герои дальше, закончи тем, что они видят. Продолжай уже рассказанное в фактическом месте; "
            "не переноси отряд в другую локацию и не вводи незарегистрированных NPC. " + STORY_RULES,
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

    stream = Stream(svc.bus, cid, msg)  # сообщение уйдёт в чат целиком, когда текст готов
    known = {ch.id for ch in newcomers}

    def clean(raw: str) -> str:
        return clean_story(raw, keep=lambda ref: ref in known)

    # знакомство отряда — часть вводной: озвучивается так же, по частям; появление новичка — без голоса
    job = _voice_job(svc, c, clean) if first else None

    feed = StoryFeed(stream, job, clean)

    call = LlmCall(campaign_id=cid, seat_id=seat_id, turn_id=None, purpose="intro", model=model)
    text = ""
    try:
        reply = await svc.llm.complete(
            msgs,
            model=model,
            tools=None,
            max_tokens=2500,
            temperature=temperature,
            api_base=api_base,
            stream_callback=feed.push,
            thinking=False,
        )
        call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
        for metric, value in reply_metrics(reply).items():
            setattr(call, metric, value)
        call.cost, call.latency_ms = reply.cost, reply.latency_ms
        text = clean(reply.text)
    except LLMError as e:
        call.error = str(e)[:2000]
    tasks = job.finish(text) if job is not None and text else []
    if job is not None and not tasks:
        job.cancel()

    async with svc.maker() as s:
        s.add(call)
        c = await s.get(Campaign, cid)
        scene = await s.get(Scene, cid)
        msg_db = await s.get(Message, msg_id)
        if text and msg_db:
            msg_db.content = await link_text(s, cid, text)
            if tasks:
                msg_db.data = voiceover.data_of([], len(tasks))
            # представленными считаем только после удачного вступления: при сбое мастер попробует на следующем ходу
            if scene:
                scene.state = {**(scene.state or {}), "introduced": _introduced(scene) + [ch.id for ch in newcomers]}
            await s.commit()
            await publish_message(svc.bus, msg_db)
            if tasks:
                _spawn(svc, voiceover.attach(svc, msg_db, tasks))
            return msg_id
        else:
            for t in tasks:
                t.cancel()
            if msg_db:
                await s.delete(msg_db)
            await s.commit()
            await svc.bus.publish(cid, envelope("message.withdrawn", cid, {"id": msg_id}), None)
            return None
