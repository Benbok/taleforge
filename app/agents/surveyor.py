"""Эскиз места по закрытому описанию мастера (решение Arty 2026-10-05: строит техническая модель).

Мастер, когда отряд приходит в новое место, пишет закрытое описание инструментом ``describe_place``: планировку,
выходы, крупные предметы, тайное. После хода дешёвая техническая модель переводит его в эскиз на клетках по 5 футов
(тот же формат, что у ``sketch_place``, app/core/sketch.py). Сервер проверяет эскиз; с ошибками модель получает
вторую попытку. Готовый эскиз помечен ``auto``: мастер видит его в таблице сцены и правит ``sketch_place``.

Эскиз не ставится, если описание успели переписать (его построит следующий запуск) или мастер после описания
нарисовал эскиз сам. Сбой модели игру не останавливает: таблица сцены напомнит нарисовать эскиз вручную.
"""

from __future__ import annotations

import copy
import logging

from pydantic import ValidationError
from sqlalchemy import select

from app.agents.character import _model
from app.agents.llm import LLMError, parser_model_for
from app.core import sketch
from app.core.campaigns import Conflict
from app.db.models import Campaign, Entity, LlmCall
from app.gateway.events import envelope
from app.tools.master import SketchArgs, link_exits, sketch_data

log = logging.getLogger(__name__)

TOOL = "submit_sketch"
ATTEMPTS = 2

SYSTEM = (
    "Ты чертёжник текстовой ролевой игры. По закрытому описанию места мастера нарисуй его эскиз для схемы игроков: "
    "сетка клеток по 5 футов, клетка [0, 0] — северо-западный угол, столбцы растут на восток, строки — на юг. "
    "Верни ровно один вызов submit_sketch.\n"
    "- cols и rows — размер места в клетках (футы делить на 5, не больше 30). Огромное открытое место — только "
    "та часть, что видна вокруг отряда.\n"
    "- party — свободная клетка, где сейчас стоит отряд: у входа, через который он пришёл, если описание это говорит.\n"
    "- walls — непроходимые клетки внутри: колонны, обвал, неровный край пещеры.\n"
    "- exits — каждый вход и выход на краю: side (n, e, s, w), at — клетка на этом краю с нуля, kind, state, "
    "beyond — что за ним. Если выход ведёт в известное место из списка, поставь его id в to. Окно и решётка — тоже "
    "выходы. Тайный выход — hidden.\n"
    "- features — крупные предметы, которые видно: прямоугольники [c0, r0, c1, r1], от северо-западной клетки к "
    "юго-восточной; предметы не налезают друг на друга и на стены. Укрытие — cover. Тайное — hidden.\n"
    "Не выдумывай того, чего нет в описании; существ не рисуй."
)


def _spec() -> dict:
    schema = copy.deepcopy(SketchArgs.model_json_schema())
    schema.pop("title", None)
    schema["properties"].pop("location_id", None)
    return {
        "type": "function",
        "function": {"name": TOOL, "description": "Сдать эскиз места.", "parameters": schema},
    }


def _neighbours(place: Entity, places: dict[str, Entity]) -> list[str]:
    out = []
    for x in (place.state or {}).get("links") or []:
        other = places.get(x.get("to") or "")
        if other is not None:
            how = ", ".join(v for v in (x.get("label"), x.get("bearing")) if v)
            out.append(f"{other.id} «{other.name}»" + (f" ({how})" if how else ""))
    for other in places.values():
        if other.location_id == place.id:
            out.append(f"{other.id} «{other.name}» (внутри этого места)")
        elif any(x.get("to") == place.id for x in (other.state or {}).get("links") or []):
            out.append(f"{other.id} «{other.name}» (путь оттуда сюда)")
    if place.location_id in places:
        parent = places[place.location_id]
        out.append(f"{parent.id} «{parent.name}» (снаружи: это место внутри него)")
    return list(dict.fromkeys(out))


async def draw(svc, cid: str, place_id: str) -> dict | None:
    """Строит эскиз места по его закрытому описанию. Возвращает эскиз или None, если строить нечего или не вышло."""
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        place = await s.get(Entity, place_id)
        st = (place.state or {}) if place is not None else {}
        if c is None or place is None or not st.get("layout"):
            return None
        rev = int(st.get("layout_rev") or 0)
        ents = (await s.scalars(select(Entity).where(Entity.campaign_id == cid))).all()
        places = {e.id: e for e in ents if e.kind == "location"}
        inside = [e.name for e in ents if e.location_id == place.id and e.kind == "object"]
        try:
            _, _, api_base, _, seat_id = await _model(s, c, None)
        except Conflict:
            log.info("эскиз %s: у кампании нет модели", place_id)
            return None
        model = parser_model_for()
        prompt = (
            f"Место: «{place.name}».\n"
            f"Как его видят герои: {place.description or 'нет'}\n\n"
            f"Закрытое описание мастера:\n{st['layout']}\n\n"
            "Известные места рядом (id для выходов):\n" + ("\n".join(_neighbours(place, places)) or "нет") + "\n\n"
            f"Уже лежит в месте: {', '.join(inside) or 'ничего'}"
        )
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    data, calls = None, []
    for _ in range(ATTEMPTS):
        call = LlmCall(campaign_id=cid, seat_id=seat_id, turn_id=None, purpose="sketch", model=model)
        calls.append(call)
        try:
            reply = await svc.llm.complete(
                msgs, model=model, tools=[_spec()], max_tokens=4000, temperature=0.2, api_base=api_base
            )
        except LLMError as e:
            call.error = str(e)[:2000]
            break
        call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
        call.cost, call.latency_ms = reply.cost, reply.latency_ms
        tc = next((t for t in reply.tool_calls if t.name == TOOL), None)
        if tc is None:
            errors = ["эскиз не сдан: нужен вызов submit_sketch"]
        else:
            try:
                data, errors = sketch_data(SketchArgs(**tc.arguments), set(places))
            except ValidationError as e:
                data, errors = None, [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:8]]
        if not errors:
            break
        data = None
        call.error = "; ".join(errors)[:2000]
        msgs.append(reply.message or {"role": "assistant", "content": reply.text})
        msgs.append({"role": "user", "content": "Сервер не принял эскиз: " + "; ".join(errors[:8]) + ". Исправь."})
    async with svc.maker() as s:
        s.add_all(calls)
        stored = False
        if data is not None:
            place = await s.get(Entity, place_id)
            st = place.state or {}
            mine = st.get("sketch") or {}
            if int(st.get("layout_rev") or 0) == rev and not (mine and not mine.get("auto") and mine.get("rev") == rev):
                ents = (await s.scalars(select(Entity).where(Entity.campaign_id == cid))).all()
                link_exits(place, data, {e.id: e for e in ents})
                place.state = {**(place.state or {}), "sketch": {**data, "auto": True, "rev": rev}}
                stored = True
        await s.commit()
    if not stored:
        if data is None:
            log.info("эскиз %s по описанию не построен", place_id)
        return None
    await svc.bus.publish(cid, envelope("map.changed", cid, {"place_id": place_id}), None)
    log.info("эскиз %s: %s", place_id, sketch.describe(data))
    return data
