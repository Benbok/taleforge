"""Техническая модель подготовки сцены (спецификация генерации сцен, §3, §4.3, §6.3, §9; поставка 5).

Модель только заполняет слоты плана, который уже выдал сервер: имена и описания обстановки, контейнеров и находок.
Роли, шаблоны, количества, носители сюжета и сами слоты задаёт policy — в схеме ответа для них нет полей. Ответ
проверяется так же, как детерминированный; невалидный получает одну корректирующую попытку, затем
детерминированный fallback из тех же ограничений (``quality = fallback``). Вызовы модели считаются в строке фазы
(``llm_attempt_count``) условной записью с токеном lease: рестарт и повтор ведущего лимит не обнуляют, а ответ,
пришедший после потери lease, не записывается.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.core.world_generation.contracts import Blocked, Plan, Proposal, ProposedObject
from app.core.world_generation.validation import MAX_DESCRIPTION, MAX_NAME, validate

log = logging.getLogger(__name__)

TOOL = "submit_scene"
TIMEOUT = 60.0  # секунд: меньше lease, ответ после него всё равно отклонит CAS
PURPOSE = "scene_generation"

SYSTEM = (
    "Ты художник-постановщик текстовой ролевой игры. Сервер уже решил, какие объекты будут в месте, и выдал слоты. "
    "Твоя задача — назвать и коротко описать каждый слот так, чтобы сцена была связной и подходила месту. "
    "Верни ровно один вызов submit_scene.\n"
    "- Заполни каждый слот из списка ровно один раз, по его slot_ref. Слоты обстановки (prop) можно пропустить.\n"
    "- Находка (item) — это указанный шаблон: можно дать вещи имя в мире и описать, как она выглядит, но не менять "
    "её суть, количество или свойства.\n"
    "- Сюжетный носитель (anchor) — имя оставь точно как дано, описание тоже не меняй по смыслу.\n"
    "- Описание — что видят герои, 1–2 фразы. Не придумывай новые факты о сюжете, злодеях, болезнях и судьбах; "
    "содержимое закрытых контейнеров не описывай как увиденное."
)


def spec(plan: Plan) -> dict[str, Any]:
    refs = [s.slot_ref for s in plan.slots]
    item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "slot_ref": {"type": "string", "enum": refs},
            "name": {"type": "string", "maxLength": MAX_NAME},
            "description": {"type": "string", "maxLength": MAX_DESCRIPTION},
        },
        "required": ["slot_ref", "name", "description"],
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"objects": {"type": "array", "items": item, "maxItems": len(refs)}},
        "required": ["objects"],
    }
    return {"type": "function", "function": {"name": TOOL, "description": "Сдать сцену.", "parameters": schema}}


def brief(plan: Plan, place: dict[str, Any], catalog) -> str:
    lines = [f"Место: «{place.get('name')}». {place.get('description') or ''}".strip()]
    if place.get("container"):
        lines.append(f"Сейчас обыскивают контейнер «{place['container']}» в этом месте: слоты — его содержимое.")
    if place.get("themes"):
        lines.append("Тон места: " + ", ".join(place["themes"]))
    if place.get("present"):
        lines.append("Уже есть в месте (не повторяй): " + ", ".join(place["present"]))
    lines.append("Слоты:")
    for s in plan.slots:
        if s.anchor_id:
            lines.append(f"- {s.slot_ref} anchor: «{s.name}» — {s.description}")
        elif s.role == "item":
            rec = catalog.find(s.template_id or "", "item_template")
            lines.append(f"- {s.slot_ref} item: {rec.name if rec else s.template_id}")
        else:
            lines.append(f"- {s.slot_ref} {s.role}: например «{s.name}»")
    return "\n".join(lines)


def to_proposal(plan: Plan, args: Any) -> Proposal:
    """Ответ модели → предложение. Роль, шаблон и носитель берутся из плана: модель их не задаёт."""
    if not isinstance(args, dict) or set(args) - {"objects"} or not isinstance(args.get("objects"), list):
        raise Blocked("invalid_proposal", "нужен объект с одним полем objects")
    out = []
    for raw in args["objects"]:
        if not isinstance(raw, dict) or set(raw) - {"slot_ref", "name", "description"}:
            raise Blocked("invalid_proposal", "у объекта допустимы только slot_ref, name, description")
        slot = plan.slot(str(raw.get("slot_ref")))
        if slot is None:
            raise Blocked("invalid_proposal", f"слота {raw.get('slot_ref')} нет в плане")
        name, desc = raw.get("name"), raw.get("description")
        if not isinstance(name, str) or not isinstance(desc, str):
            raise Blocked("invalid_proposal", f"слот {slot.slot_ref}: name и description — строки")
        out.append(
            ProposedObject(slot.slot_ref, slot.role, name.strip(), desc.strip(), slot.template_id, slot.anchor_id)
        )
    proposal = Proposal(1, tuple(out))
    validate(plan, proposal)
    return proposal


@dataclass
class Attempt:
    """Один вызов модели для учёта в LlmCall."""

    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    error: str | None = None


async def ask(llm, plan: Plan, place: dict[str, Any], catalog, *, model: str, api_base: str | None, msgs: list):
    """Один вызов модели. Возвращает (предложение или None, учёт, ошибка для корректирующей попытки)."""
    if not msgs:
        msgs += [{"role": "system", "content": SYSTEM}, {"role": "user", "content": brief(plan, place, catalog)}]
    attempt = Attempt(model=model)
    try:
        reply = await asyncio.wait_for(
            llm.complete(msgs, model=model, tools=[spec(plan)], max_tokens=3000, temperature=0.7, api_base=api_base),
            TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 — сбой или таймаут модели ведёт к fallback, а не к ошибке хода
        attempt.error = f"{type(e).__name__}: {e}"[:2000]
        return None, attempt, None
    attempt.model = reply.model or model
    attempt.tokens_in, attempt.tokens_out = reply.tokens_in, reply.tokens_out
    attempt.cost, attempt.latency_ms = reply.cost or 0.0, reply.latency_ms or 0
    tc = next((t for t in reply.tool_calls if t.name == TOOL), None)
    try:
        if tc is None:
            raise Blocked("invalid_proposal", "нужен вызов submit_scene")
        return to_proposal(plan, tc.arguments), attempt, None
    except Blocked as e:
        attempt.error = e.detail[:2000]
        msgs.append(reply.message or {"role": "assistant", "content": reply.text})
        msgs.append({"role": "user", "content": f"Сервер не принял сцену: {e.detail}. Исправь и сдай заново."})
        return None, attempt, e.detail
