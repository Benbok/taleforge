"""Характер, который живёт (ТЗ, раздел 5.2; этап 9б): помощник анкеты, пробные сцены и летопись характера.

- «Помочь» дописывает пустые поля анкеты по классу, происхождению, миру и тому, что уже написано. Заполненное
  не трогает: сервер берёт из ответа модели только пустые поля.
- «Проверить» прогоняет три короткие сцены и показывает, что герой (или мастер) скажет и сделает. Анкету можно
  передать несохранённой: так владелец правит и проверяет, не сохраняя каждый раз.
- Летопись: после сессии и сразу после сильного события дешёвая модель пишет 0–2 записи «что изменилось и
  почему» для героев, которых ведёт ИИ, и для ИИ-мастера. Ядро анкеты летопись не меняет.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select

from app.agents.llm import LLMError, model_for, parser_model_for
from app.content.catalog import campaign_catalog
from app.core import persona
from app.core.campaigns import Conflict, default_model_profile, master_seat
from app.db.models import AgentConfig, Campaign, Character, LlmCall, ModelProfile, PersonaNote

log = logging.getLogger(__name__)

HERO_SCENES = [
    (
        "Спор в отряде",
        "Отряд спорит, идти ли короткой дорогой через заброшенный рудник или день обходить горы. "
        "Спутник требует, чтобы твой герой встал на его сторону.",
    ),
    ("Соблазн", "Раненый торговец просит помощи. Рядом лежит его открытый кошель, и никто не смотрит."),
    (
        "Опасность",
        "Мост под отрядом трещит, а на том берегу из тумана выходит что-то большое. У героя один миг, чтобы решить.",
    ),
]
MASTER_SCENES = [
    ("Описание места", "Отряд впервые входит в придорожную таверну поздним вечером. Опиши, что они видят."),
    ("Реакция NPC", "Герой грубо требует у стражника пропустить отряд без досмотра. Опиши, как стражник отвечает."),
    ("Провал героя", "Герой пытается перепрыгнуть расщелину и проваливает проверку. Опиши, что происходит."),
]
MAX_NOTES = 2


# --- модель ---


async def _model(s, c: Campaign, seat_id: str | None) -> tuple[str, str, str | None, float, str | None]:
    """(провайдер, модель, api_base, температура, место для учёта): своя модель ИИ-игрока, иначе модель мастера,
    иначе профиль по умолчанию из админки."""
    for seat in [x for x in c.seats if x.id == seat_id] + [master_seat(c)]:
        if seat.occupant_type == "agent" and seat.agent_config_id:
            cfg = await s.get(AgentConfig, seat.agent_config_id)
            api_base = (cfg.settings or {}).get("api_base")
            return cfg.provider, model_for(cfg.provider, cfg.model), api_base, cfg.temperature, seat.id
    p = await default_model_profile(s)
    if p is not None:
        return p.provider, model_for(p.provider, p.model), p.api_base, p.temperature, None
    raise Conflict("нет модели: у кампании живой мастер, а в админке нет профиля модели по умолчанию")


async def _complete(
    svc, cid: str | None, seat_id: str | None, purpose: str, model, api_base, temperature, msgs, tools=None
):
    try:
        reply = await svc.llm.complete(
            msgs, model=model, tools=tools, max_tokens=1500, temperature=temperature, api_base=api_base
        )
    except LLMError as e:
        if cid:
            call = LlmCall(
                campaign_id=cid, seat_id=seat_id, turn_id=None, purpose=purpose, model=model, error=str(e)[:2000]
            )
            async with svc.maker() as s:
                s.add(call)
                await s.commit()
        raise Conflict(f"модель не ответила: {str(e)[:300]}") from e

    if cid:
        call = LlmCall(
            campaign_id=cid,
            seat_id=seat_id,
            turn_id=None,
            purpose=purpose,
            model=reply.model,
            tokens_in=reply.tokens_in,
            tokens_out=reply.tokens_out,
            cost=reply.cost,
            latency_ms=reply.latency_ms,
        )
        async with svc.maker() as s:
            s.add(call)
            await s.commit()
    return reply


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


# --- о ком речь ---


async def hero_basics(s, c: Campaign, ch: Character) -> str:
    cat = await campaign_catalog(s, c)
    names = []
    for key, kind in (("class_id", "class"), ("origin_id", "origin")):
        rec = cat.find((ch.sheet or {}).get(key) or "", kind)
        names.append(rec.name if rec else "")
    parts = [f"Герой: {ch.name}. Класс: {names[0] or '—'}. Происхождение: {names[1] or '—'}."]
    if ch.public_bio:
        parts.append(f"Внешность и история: {ch.public_bio}")
    if ch.private_backstory:
        parts.append(f"Тайная предыстория: {ch.private_backstory}")
    return "\n".join(parts)


async def world_basics(s, c: Campaign) -> str:
    cat = await campaign_catalog(s, c)
    pack = getattr(cat, "pack_name", None) or ""
    parts = [f"Кампания «{c.name}»." + (f" Мир: {pack}." if pack else "")]
    if c.public_intro:
        parts.append(c.public_intro)
    return " ".join(parts)


def _sheet_text(sheet: dict, master: bool) -> str:
    return persona.render(sheet, [], master) or "(анкета пуста)"


# --- «Помочь» ---


async def help_fill(svc, cid: str, sheet: dict, *, character_id: str | None) -> dict[str, Any]:
    """Дописывает пустые поля анкеты. character_id пуст — анкета ИИ-мастера."""
    master = character_id is None
    sheet = persona.normalize(sheet, master)
    fields = persona.fields_for(master)
    empty = [k for k in fields if not sheet["fields"].get(k)]
    need_text = not sheet["text"]
    if not empty and not need_text:
        return sheet
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        ch = await s.get(Character, character_id) if character_id else None
        about = await hero_basics(s, c, ch) if ch else "Это анкета ИИ-мастера кампании: его манера вести игру."
        world = await world_basics(s, c)
        provider, model, api_base, temperature, seat_id = await _model(s, c, ch.seat_id if ch else None)
    props: dict[str, Any] = {k: {"type": "string", "description": f"{fields[k][0]}: {fields[k][1]}"} for k in empty}
    if need_text:
        props["text"] = {"type": "string", "description": "Свободный текст: кто он и как смотрит на мир, 3–6 фраз"}
    spec = _tool("fill_persona", "Заполнить пустые поля анкеты характера.", props, list(props))
    who = "мастера" if master else "героя"
    msgs = [
        {
            "role": "system",
            "content": (
                f"Ты помогаешь дописать анкету характера {who} для текстовой ролевой игры. Пиши по-русски, конкретно "
                "и живо, без штампов и общих слов. Опирайся на то, что уже написано, и не противоречь ему. "
                "Делай характер неповторимым: противоречия, привычки, конкретные детали."
            ),
        },
        {
            "role": "user",
            "content": f"{world}\n\n{about}\n\nУже написано:\n{_sheet_text(sheet, master)}\n\nЗаполни пустые поля.",
        },
    ]
    reply = await _complete(svc, cid, seat_id, "persona_help", model, api_base, temperature, msgs, [spec])
    call = next((t for t in reply.tool_calls if t.name == "fill_persona"), None)
    got = call.arguments if call else {}
    if not isinstance(got, dict) or not got:
        raise Conflict("модель не предложила ничего: попробуйте ещё раз")
    out = {**sheet, "fields": dict(sheet["fields"])}
    for k in empty:  # заполненное владельцем не переписывается
        if isinstance(got.get(k), str) and got[k].strip():
            out["fields"][k] = got[k].strip()[: persona.FIELD_MAX]
    if need_text and isinstance(got.get("text"), str):
        out["text"] = got["text"].strip()[: persona.TEXT_MAX]
    return persona.normalize(out, master)


# --- «Проверить» ---


async def try_scenes(svc, cid: str, sheet: dict, *, character_id: str | None) -> list[dict[str, str]]:
    """Три пробные сцены: что скажет и сделает герой (или как опишет мастер)."""
    from app.agents.player import SYSTEM

    master = character_id is None
    sheet = persona.normalize(sheet, master)
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        ch = await s.get(Character, character_id) if character_id else None
        notes = await persona.notes_of(s, cid, character_id)
        about = await hero_basics(s, c, ch) if ch else ""
        world = await world_basics(s, c)
        provider, model, api_base, temperature, seat_id = await _model(s, c, ch.seat_id if ch else None)
    character = persona.render(sheet, notes, master)
    if master:
        system = "Ты — мастер текстовой ролевой игры по D&D 5e. Пиши по-русски, 3–6 предложений, в своей манере:\n" + (
            character or "манера не задана"
        )
        scenes = MASTER_SCENES
    else:
        system = SYSTEM + "\n\n" + about + ("\nХарактер:\n" + character if character else "")
        scenes = HERO_SCENES
    out = []
    for title, text in scenes:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": f"{world}\n\nСцена: {text}"}]
        reply = await _complete(svc, cid, seat_id, "persona_test", model, api_base, temperature, msgs)
        out.append({"scene": title, "situation": text, "reply": (reply.text or "").strip() or "—"})
    return out


async def try_preset_scenes(svc, profile_id: str | None, sheet: dict, style: str | None = None) -> list[dict[str, str]]:
    """Три пробные сцены для пресета мастера (без привязки к конкретной кампании)."""
    async with svc.maker.begin() as s:
        if profile_id:
            p = await s.get(ModelProfile, profile_id)
        else:
            p = await default_model_profile(s)
        if p is not None:
            model, api_base, temperature = (
                model_for(p.provider, p.model),
                p.api_base,
                p.temperature,
            )
        else:
            model, api_base, temperature = model_for("claude", ""), None, 0.8

    sheet = persona.normalize(sheet, master=True)
    character = persona.render(sheet, [], master=True)
    if style and style.strip():
        character = (style.strip() + "\n\n" + character) if character else style.strip()

    system = "Ты — мастер текстовой ролевой игры по D&D 5e. Пиши по-русски, 3–6 предложений, в своей манере:\n" + (
        character or "манера не задана"
    )
    out = []
    for title, text in MASTER_SCENES:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": f"Сцена: {text}"}]
        reply = await _complete(svc, None, None, "persona_test", model, api_base, temperature, msgs)
        out.append({"scene": title, "situation": text, "reply": (reply.text or "").strip() or "—"})
    return out


# --- летопись ---

CHRONICLE_SYSTEM = (
    "Ты ведёшь летопись характера в текстовой ролевой игре. По тому, что произошло, реши, изменился ли характер, "
    "и запиши 0–2 изменения: что изменилось и почему, одной фразой каждое, например «после гибели Торина стал "
    "осторожнее и больше не шутит о смерти». Меняй только то, что правда сдвинулось от событий; мелочи не пиши. "
    "Неизменные черты (помечены «неизменно») не меняются никогда. Если ничего не изменилось, верни пустой список."
)


def chronicle_spec() -> dict:
    note = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "что изменилось в характере"},
            "cause": {"type": "string", "description": "почему: какое событие"},
        },
        "required": ["text", "cause"],
    }
    return _tool(
        "write_chronicle",
        "Записи летописи характера: 0–2 изменения.",
        {"notes": {"type": "array", "items": note, "maxItems": MAX_NOTES}},
        ["notes"],
    )


async def chronicle(svc, cid: str, reason: str, *, session_id: str | None = None) -> int:
    """Летопись после сессии (``reason`` = «сессия закончилась») или сильного события. Возвращает число записей."""
    from app.agents import memory

    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        if c is None:
            return 0
        ms = master_seat(c)
        heroes = [
            ch
            for ch in (await s.scalars(select(Character).where(Character.campaign_id == cid))).all()
            if ch.status in ("approved", "active", "dead")
            and any(x.id == ch.seat_id and x.occupant_type == "agent" and x.role == "player" for x in c.seats)
        ]
        subjects: list[tuple[str | None, str, dict, list]] = []
        for ch in heroes:
            subjects.append((ch.id, ch.name, ch.persona or {}, await persona.notes_of(s, cid, ch.id)))
        if ms.occupant_type == "agent" and ms.agent_config_id:
            cfg = await s.get(AgentConfig, ms.agent_config_id)
            sheet = (cfg.settings or {}).get("character") or {}
            subjects.append((None, "ИИ-мастер", sheet, await persona.notes_of(s, cid, None)))
        if not subjects:
            return 0
        last = await memory.latest(s, cid)
        rows = await memory.public_messages(s, cid, max(0, c.last_seq - 40))
        happened = "\n".join(f"- {m.content[:300]}" for m in rows if m.kind in ("narration", "action", "speech"))
        recap = (last.content or {}).get("recap", "") if last else ""
        try:
            provider, model, api_base, _, seat_id = await _model(s, c, None)
        except Conflict:
            return 0
        model = parser_model_for(provider, model)
    written = 0
    for character_id, name, sheet, notes in subjects:
        master = character_id is None
        msgs = [
            {"role": "system", "content": CHRONICLE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Повод: {reason}.\nЧей характер: {name}.\nАнкета и летопись:\n"
                    f"{persona.render(sheet, notes, master) or '(анкета пуста)'}\n\n"
                    f"Сводка кампании: {recap or 'нет'}\n\nПоследнее за столом:\n{happened or 'нет'}"
                ),
            },
        ]
        try:
            reply = await _complete(svc, cid, seat_id, "chronicle", model, api_base, 0.3, msgs, [chronicle_spec()])
        except Conflict:
            log.info("летопись %s: модель не ответила", name)
            continue
        call = next((t for t in reply.tool_calls if t.name == "write_chronicle"), None)
        items = (call.arguments or {}).get("notes") if call else None
        items = [x for x in (items or []) if isinstance(x, dict) and str(x.get("text") or "").strip()][:MAX_NOTES]
        if not items:
            continue
        async with svc.maker() as s:
            for x in items:
                s.add(
                    PersonaNote(
                        campaign_id=cid,
                        character_id=character_id,
                        session_id=session_id,
                        text=str(x["text"]).strip()[:500],
                        cause=str(x.get("cause") or "").strip()[:300] or reason,
                        source="session" if session_id else "event",
                    )
                )
            await s.commit()
        written += len(items)
    if written:
        log.info("летопись кампании %s: %s записей (%s)", cid, written, json.dumps(reason, ensure_ascii=False))
    return written
