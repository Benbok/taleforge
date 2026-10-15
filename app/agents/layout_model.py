"""Техническая модель структуры комплекса (спецификация 2026-10-12, §3.2, §8; поставка 3).

Модель предлагает замысел — части, связи, проходы, детали, полосы рельефа — по мандату места. Координаты, endpoints и
края считает детерминированный provider поставки 1: невозможную геометрию модель выдать не может, её ошибки — это
ошибки ``obligations``/``validate``, они возвращаются одной корректирующей попыткой. Секреты каркаса в запрос не
идут: тайность задают флаги частей. Лимит вызовов и учёт — в исполнителе фазы (app/core/layout/executor.py).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any, get_args

from pydantic import ValidationError

from app.agents.world_generator import Attempt
from app.core.layout.contracts import MAX_AREAS, MAX_SIDE, LayoutError
from app.core.layout.intent import BandIntent, DetailIntent, LayoutIntent, PartIntent
from app.core.layout.spatial import Mandate, obligations
from app.core.world_generation.contracts import Blocked

TOOL = "submit_layout"
PURPOSE = "location_layout"
TIMEOUT = 60.0  # секунд: меньше lease фазы, опоздавший ответ всё равно отклонит CAS
MAX_IN = 6000  # входных токенов на вызов (спецификация §8)
MAX_OUT = 3000  # выходных токенов вместе с рассуждениями
CHARS_PER_TOKEN = 3.2  # как оценка архитектора (app/agents/architect.py)

SYSTEM = (
    "Ты планировщик пространства текстовой ролевой игры. Сервер дал обязательные части места, подходы и привязки. "
    "Предложи устройство комплекса одним вызовом submit_layout.\n"
    "- Каждая обязательная часть — ровно с тем part_ref, тайная — secret=true (не может быть открытой местностью), "
    "«уровнем ниже» — level=-1 и passage_kind=stairs, сюжетная цель — required=true. "
    "Первая обязательная часть — entry.\n"
    "- Можно добавить коридоры и комнаты (всего до 12 частей), но не убирать обязательные.\n"
    "- connects_to — часть выше по списку, side — с какой стороны родителя (n, e, s, w).\n"
    "- Каждую привязку из списка укажи ровно в одной части, в её anchors.\n"
    "- Сохраняй окружение обязательных частей: открытая местность — outdoor, помещения — indoor. "
    "Если заданы форма или материал, сохрани их в shape и material. "
    "Для каждой части предложи хотя бы две характерные декоративные детали; учитывай назначение места. "
    "Детали не должны перекрывать проходы. Не делай маленькую пустую комнату вместо целого места.\n"
    "- Подходы ведут снаружи к частям (kind: edge для дорог и открытых границ, door/gate/arch для входов); "
    "outside_id не задаётся.\n"
    "- Дорога, тропа и ручей — полосы bands в клетках плана (координаты клеток должны попадать внутрь "
    "участков; если не уверен в клетках, оставь bands пустым список []).\n"
    "- Названия (name, public_name, passage_name) видят игроки: без тайн и спойлеров. Не придумывай механику, "
    "существ и сокровища: только устройство места."
)


def estimate(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def _enum(model, field: str) -> list[str]:
    return list(get_args(model.model_fields[field].annotation))


def spec(m: Mandate) -> dict[str, Any]:
    keys = [h.key for h in m.holders()]
    detail = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "detail_ref": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{0,31}$"},
            "name": {"type": "string", "maxLength": 60},
            "kind": {"type": "string", "enum": _enum(DetailIntent, "kind")},
            "cells": {
                "type": "array",
                "maxItems": 4,
                "items": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "integer"}},
            },
            "solid": {"type": "boolean"},
        },
        "required": ["detail_ref", "name", "cells"],
    }
    part = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "part_ref": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{0,31}$"},
            "role": {"type": "string", "maxLength": 32},
            "name": {"type": "string", "maxLength": 128},
            "public_name": {"type": "string", "maxLength": 128},
            "description": {"type": "string", "maxLength": 1000},
            "environment": {"type": "string", "enum": _enum(PartIntent, "environment")},
            "shape": {"type": "string", "enum": _enum(PartIntent, "shape")},
            "material": {"type": "string", "enum": ["stone", "earth", "grass", "water", "wood"]},
            "size": {"type": "string", "enum": _enum(PartIntent, "size")},
            "cols": {"type": "integer", "minimum": 1, "maximum": MAX_SIDE},
            "rows": {"type": "integer", "minimum": 1, "maximum": MAX_SIDE},
            "level": {"type": "integer", "minimum": -3, "maximum": 3},
            "connects_to": {"type": "string"},
            "side": {"type": "string", "enum": ["n", "e", "s", "w"]},
            "passage_kind": {"type": "string", "enum": _enum(PartIntent, "passage_kind")},
            "passage_name": {"type": "string", "maxLength": 60},
            "passage_state": {"type": "string", "enum": _enum(PartIntent, "passage_state")},
            "secret": {"type": "boolean"},
            "required": {"type": "boolean"},
            "anchors": {"type": "array", "items": {"type": "string", "enum": keys}},
            "details": {"type": "array", "maxItems": 16, "items": detail},
        },
        "required": ["part_ref", "name", "public_name"],
    }
    approach = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "part_ref": {"type": "string"},
            "side": {"type": "string", "enum": ["n", "e", "s", "w"]},
            "kind": {"type": "string", "enum": ["edge", "door", "gate", "arch", "passage", "gap"]},
            "public_name": {"type": "string", "maxLength": 60},
            "band": {"type": "string"},
            "width": {"type": "integer", "minimum": 1, "maximum": MAX_SIDE},
        },
        "required": ["part_ref", "side", "public_name"],
    }
    band = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "band_ref": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{0,31}$"},
            "kind": {"type": "string", "enum": _enum(BandIntent, "kind")},
            "axis": {"type": "string", "enum": _enum(BandIntent, "axis")},
            "at": {"type": "integer"},
            "width": {"type": "integer", "minimum": 1, "maximum": 4},
            "start": {"type": "integer"},
            "end": {"type": "integer"},
        },
        "required": ["band_ref", "kind", "axis", "at"],
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "entry": {"type": "string"},
            "parts": {"type": "array", "minItems": 1, "maxItems": MAX_AREAS, "items": part},
            "approaches": {"type": "array", "minItems": 1, "maxItems": 8, "items": approach},
            "bands": {"type": "array", "maxItems": 6, "items": band},
        },
        "required": ["entry", "parts", "approaches"],
    }
    return {
        "type": "function",
        "function": {
            "name": TOOL,
            "description": "Сдать устройство места.",
            "parameters": schema,
        },
    }


def _lines(m: Mandate, *, mood: bool, purposes: bool) -> list[str]:
    sp = m.spatial
    lines = [f"Место: «{m.place}». Окружение: {sp.environment}; масштаб: {sp.scale}."]
    if mood and m.mood:
        lines.append(f"Настроение: {m.mood}")
    lines.append("Обязательные части (part_ref «название»):")
    for i, p in enumerate(sp.parts):
        flags = [
            x
            for x, on in (
                ("вход", i == 0),
                ("открытая местность", p.outdoor),
                ("уровнем ниже", p.below),
                ("тайная — secret=true", p.secret),
                ("сюжетная цель — required=true", p.required),
            )
            if on
        ]
        what = f" — {p.purpose}" if purposes and p.purpose else ""
        if p.shape is not None:
            flags.append(f"форма — {p.shape}")
        if p.material is not None:
            flags.append(f"материал — {p.material}")
        lines.append(f"- {p.ref} «{p.name}»{what}" + (f" [{'; '.join(flags)}]" if flags else ""))
    lines.append("Подходы снаружи: " + "; ".join(f"«{a.name}» ({a.kind})" for a in sp.approaches))
    if m.holders():
        lines.append(
            "Привязки (каждую — в anchors ровно одной части): " + "; ".join(f"{h.key} «{h.name}»" for h in m.holders())
        )
    return lines


def input_estimate(m: Mandate, msgs: list) -> int:
    """Оценка всего запроса: история с аргументами инструментов и схема submit_layout."""
    return estimate(json.dumps({"messages": msgs, "tools": [spec(m)]}, ensure_ascii=False))


def brief(m: Mandate) -> str | None:
    """Запрос в бюджете ``MAX_IN``: сначала уходит настроение, потом пояснения частей. Обязательное не урезается;
    не помещается и оно — None (исполнитель уходит в fallback ``context_budget``)."""
    for mood, purposes in ((True, True), (False, True), (False, False)):
        text = "\n".join(_lines(m, mood=mood, purposes=purposes))
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]
        if input_estimate(m, msgs) <= MAX_IN:
            return text
    return None


def to_intent(m: Mandate, args: Any) -> LayoutIntent:
    """Ответ модели → замысел. Подходы всегда ведут в само место: outside_id модель не задаёт."""
    if not isinstance(args, dict) or set(args) - {"entry", "parts", "approaches", "bands"}:
        raise Blocked("invalid_proposal", "допустимы только поля entry, parts, approaches, bands")
    for ap in args.get("approaches") or []:
        if isinstance(ap, dict) and ap.get("outside_id") is not None:
            raise Blocked("invalid_proposal", "подход: outside_id не задаётся, снаружи — само место")
    try:
        intent = LayoutIntent.model_validate({**args, "schema_version": 1})
    except ValidationError as e:
        why = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:6])
        raise Blocked("invalid_proposal", why) from e
    errors = obligations(intent, m)
    if errors:
        raise Blocked("invalid_proposal", "; ".join(errors[:8]))
    return intent


async def ask(
    llm, m: Mandate, *, model: str, api_base: str | None, msgs: list, check: Callable[[LayoutIntent], None]
) -> tuple[LayoutIntent | None, Attempt, str | None]:
    """Один вызов. (замысел или None, учёт, причина для корректирующей попытки или None — сбой модели)."""
    if not msgs:
        text = brief(m)
        if text is None:
            raise Blocked("context_budget", "обязательные факты места не помещаются в бюджет запроса")
        msgs += [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]
    if input_estimate(m, msgs) > MAX_IN:
        raise Blocked("context_budget", "запрос с историей исправления не помещается в бюджет")
    attempt = Attempt(model=model)
    try:
        reply = await asyncio.wait_for(
            llm.complete(
                msgs,
                model=model,
                tools=[spec(m)],
                tool_choice="required",
                max_tokens=MAX_OUT,
                temperature=0.7,
                api_base=api_base,
            ),
            TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 — сбой или таймаут модели ведёт к fallback, а не к ошибке хода
        attempt.error = f"{type(e).__name__}: {e}"[:2000]
        return None, attempt, None
    attempt.model = reply.model or model
    attempt.tokens_in, attempt.tokens_out = reply.tokens_in, reply.tokens_out
    attempt.tokens_reasoning = reply.reasoning_tokens
    attempt.tokens_cached = reply.tokens_cached
    attempt.cost_known = reply.cost_known
    attempt.cost, attempt.latency_ms = reply.cost or 0.0, reply.latency_ms or 0
    tc = next((t for t in reply.tool_calls if t.name == TOOL), None)
    try:
        if tc is None:
            raise Blocked("invalid_proposal", "нужен вызов submit_layout")
        intent = to_intent(m, tc.arguments)
        try:
            check(intent)
        except LayoutError as e:
            raise Blocked("invalid_proposal", "; ".join(e.errors[:8])) from e
        return intent, attempt, None
    except Blocked as e:
        attempt.error = e.detail[:2000]
        msgs.append(reply.message or {"role": "assistant", "content": reply.text})
        msgs.append({"role": "user", "content": f"Сервер не принял план: {e.detail}. Исправь и сдай заново."})
        return None, attempt, e.detail
