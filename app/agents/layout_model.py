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
from app.core.layout.contracts import MAX_SIDE, LayoutError
from app.core.layout.intent import DETAIL_VISUAL_KEYS, BandIntent, DetailIntent, LayoutIntent, PartIntent
from app.core.layout.spatial import Mandate, obligations
from app.core.layout.template_roles import infer_role
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
    "«уровнем ниже» — level=-1, сюжетная цель — required=true. "
    "У остальных обязательных частей secret=false. Первая обязательная часть — entry, level=0.\n"
    "- Можно добавить коридоры и комнаты (всего до 12 частей), но не убирать обязательные.\n"
    "- connects_to — part_ref части выше по списку, side — с какой стороны родителя (n, e, s, w). "
    "Лестница (stairs) и люк (hatch) соединяют ТОЛЬКО разные level. Между частями одного level — "
    "door, arch, passage или gap, даже если обе под землёй. Например, crypt level=-1 → vault level=-1: door.\n"
    "- anchors — только точные ключи привязок из мандата, не названия частей или подходов. "
    "Каждую размести ровно один раз, в части с открытым путём от entry, не в тайной части. "
    "Если привязок нет, поле anchors не задавай. Тайные части: required=false, без привязок.\n"
    "- Сохраняй окружение обязательных частей: открытая местность — outdoor, помещения — indoor. "
    "Если заданы форма или материал, сохрани их в shape и material. "
    "Для открытой местности обычно shape=open; corridor — только узкий коридор с min(cols,rows)<=2. "
    "Обычная комната — около 7×8 клеток, большой зал — 10×12, открытый участок — 14×12; "
    "кладовая меньше, коридор остаётся узким. Не сжимай весь комплекс в маленькие комнаты. "
    "Наполнение следует назначению и описанию части: пустота тоже осмысленна, details=[] допустим. "
    "Камера заключённых (role=prison_cell) скудная: 0–2 детали, грубые нары или обломки; "
    "не добавляй стеллажи, кресла, шкафы и удобства без указания в сцене. "
    "role обозначает назначение (prison_cell, library, kitchen), а не положение start/entry. "
    "Для обжитой обычной части предложи 4–6 характерных деталей, для большого зала 6–8; "
    "пустые помещения и коридоры не нужно заполнять ради количества. "
    "Собирай логичные группы: стол со скамьями, кровать с сундуком, стеллажи со штабелями, "
    "скальные островки с мхом. Несколько самостоятельных предметов — отдельные детали. "
    "У каждой детали свой detail_ref, уникальный внутри части (например pillar_1, pillar_2). "
    "Выбери для неё подходящий visual_key из схемы: bed — кровать, nest — звериная лежка, "
    "hearth/torch — огонь, lichen/glow — природное свечение; rock — скала, pillar — колонна. "
    "cells детали — локальные включительные прямоугольники [c0,r0,c1,r1] внутри cols×rows. "
    "Начинай с компактных деталей по 1–2 клетки; стол может быть 2×2, кровать 1×2. "
    "Оставляй проходы между группами шириной 1–2 клетки и свободные подходы к выходам; "
    "для больших деталей увеличь помещение. Не делай маленькую пустую комнату вместо целого места.\n"
    "- Настенные факелы (feature:torch) размещай вдоль настоящих стен, не в центре комнаты; "
    "для обычного освещения распределяй несколько источников по разным стенам с учётом размера. "
    "Очаг остаётся на своём месте. lighting=normal — обычное освещение при наличии огня; "
    "если сцена намеренно оставляет тёмные углы или единственный факел, задай lighting=dim; "
    "для неосвещённой сцены — lighting=dark. Сервер не добавляет источники при dim/dark.\n"
    "- Подходы ведут снаружи к частям (kind: edge для дорог и открытых границ, door/gate/arch для входов); "
    "outside_id не задаётся. Сначала выбери для подхода свободную внешнюю сторону части, затем "
    "размещай соседей: не пристраивай часть снаружи этой стороны. Для entry с подходом side=w "
    "размещай соседей с n/e/s. Для door и passage ширина width=1; широкий вход — gate, arch, gap или edge.\n"
    "- Дорога, тропа и ручей — полосы bands в клетках плана (координаты клеток должны попадать внутрь "
    "участков; если не уверен в клетках, оставь bands пустым списком []). "
    "approaches[].band — необязательная ССЫЛКА на существующий bands[].band_ref, не название подхода. "
    "При bands=[] поле band в подходах НЕ задавай. Полоса we выходит на e/w, ns — на n/s.\n"
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
            "detail_ref": {
                "type": "string",
                "pattern": r"^[a-z][a-z0-9_]{0,31}$",
                "description": "Уникален внутри части: pillar_1, pillar_2, не два одинаковых pillar.",
            },
            "name": {"type": "string", "maxLength": 60},
            "kind": {"type": "string", "enum": _enum(DetailIntent, "kind")},
            # Ключи — в описании, не в enum: вложенный в parts/details enum из десятков значений Gemini
            # в режиме tool_choice=required отклоняет всю схему (400 INVALID_ARGUMENT). Неизвестный ключ
            # сервер отбрасывает в to_intent.
            "visual_key": {
                "type": "string",
                "description": "Рисунок детали, один из: "
                + ", ".join(DETAIL_VISUAL_KEYS)
                + ". Только внешний вид: не меняет solid или проходимость.",
            },
            "cells": {
                "type": "array",
                "description": "Прямоугольники [c0,r0,c1,r1] включительно, НЕ x,y,width,height. c1>=c0 и r1>=r0.",
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
            "shape": {
                "type": "string",
                "enum": _enum(PartIntent, "shape"),
                "description": "Сохрани форму из мандата. corridor: min(cols,rows)<=2; открытая местность обычно open.",
            },
            "material": {"type": "string", "enum": ["stone", "earth", "grass", "water", "wood"]},
            "size": {"type": "string", "enum": _enum(PartIntent, "size")},
            "cols": {"type": "integer", "minimum": 1, "maximum": MAX_SIDE},
            "rows": {"type": "integer", "minimum": 1, "maximum": MAX_SIDE},
            "lighting": {
                "type": "string",
                "enum": ["normal", "dim", "dark"],
                "description": "dim/dark сохраняют намеренный полумрак/темноту без добавления источников света.",
            },
            "level": {"type": "integer", "minimum": -3, "maximum": 3},
            "connects_to": {"type": "string", "description": "part_ref родителя выше по списку, не его название."},
            "side": {"type": "string", "enum": ["n", "e", "s", "w"], "description": "Сторона родителя."},
            "passage_kind": {
                "type": "string",
                "enum": _enum(PartIntent, "passage_kind"),
                "description": "stairs/hatch только при разных level; при одинаковых — door/arch/passage/gap.",
            },
            "passage_name": {"type": "string", "maxLength": 60},
            "passage_state": {"type": "string", "enum": _enum(PartIntent, "passage_state")},
            "secret": {"type": "boolean"},
            "required": {"type": "boolean"},
            "details": {"type": "array", "maxItems": 16, "items": detail},
        },
        "required": ["part_ref", "name", "public_name"],
    }
    if keys:
        part["properties"]["anchors"] = {
            "type": "array",
            "description": "Только ключи из enum. Каждый ровно раз, в доступной нетайной части.",
            "items": {"type": "string", "enum": keys},
        }
    approach = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "part_ref": {"type": "string"},
            "side": {
                "type": "string",
                "enum": ["n", "e", "s", "w"],
                "description": "Свободная внешняя сторона: снаружи не должно быть другого участка.",
            },
            "kind": {"type": "string", "enum": ["edge", "door", "gate", "arch", "passage", "gap"]},
            "public_name": {"type": "string", "maxLength": 60},
            "band": {
                "type": "string",
                "description": "Ссылка на bands[].band_ref. Не название подхода! Если bands пуст, НЕ задавай это поле.",
                "pattern": r"^[a-z][a-z0-9_]{0,31}$",
            },
            "width": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_SIDE,
                "description": "Для door/passage только 1; шире — gate/arch/gap/edge.",
            },
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
            # Без maxItems: поверх вложенных ограниченных details/cells Gemini отклоняет схему целиком
            # (400 INVALID_ARGUMENT). Лимит MAX_AREAS — в SYSTEM, проверяет LayoutIntent.
            "parts": {"type": "array", "minItems": 1, "items": part},
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
        flags.extend((f"environment={'outdoor' if p.outdoor else 'indoor'}", f"secret={str(p.secret).lower()}"))
        role = p.role
        if role is None or role in {"room", "start", "entry", "area", "generic"}:
            role = infer_role(p.ref, p.name, p.purpose) or role
        if role is not None:
            flags.append(f"role={role}")
        if p.lighting is not None:
            flags.append(f"lighting={p.lighting} — задано сценой, сохрани")
        if p.below:
            flags.append("level=-1")
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
    else:
        lines.append("Привязок нет: поле anchors не задавай. Названия частей и подходов не являются привязками.")
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
    for part in args.get("parts") or []:
        for detail in (part.get("details") or []) if isinstance(part, dict) else []:
            if isinstance(detail, dict) and detail.get("visual_key") not in (None, *DETAIL_VISUAL_KEYS):
                detail["visual_key"] = None  # выдуманный рисунок не стоит корректирующей попытки
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
    intent = None
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
        msgs.append({"role": "user", "content": _correction(m, tc.arguments if tc else None, intent, e.detail)})
        return None, attempt, e.detail


def _correction(m: Mandate, args: Any, intent: LayoutIntent | None, detail: str) -> str:
    """Explain the rejected references/geometry without changing or weakening the proposal."""
    lines = [f"Сервер не принял план: {detail}."]
    if "тайн" in detail or "required" in detail:
        for part in m.spatial.parts:
            if part.secret:
                lines.append(f"{part.ref}: secret=true, required=false, anchors=[] — точные флаги тайной части.")
        lines.append(
            "Обязательные части и все anchors размести на открытом пути от entry: "
            "их connects_to и вся цепочка родителей должны вести через открытые части. "
            "Тайная часть не может быть единственным путём к обязательной."
        )
    if "полос" in detail or "band" in detail:
        bands = args.get("bands") if isinstance(args, dict) else None
        refs = (
            [b.get("band_ref") for b in bands if isinstance(b, dict) and b.get("band_ref")]
            if isinstance(bands, list)
            else []
        )
        lines.append(
            "approaches[].band — только ссылка на bands[].band_ref. "
            f"Сейчас band_ref: {json.dumps(refs, ensure_ascii=False)}. "
            "Не указывай название подхода; если подходу не нужна полоса, убери band, а не выдумывай ссылку."
        )
    if "привязк" in detail or "anchors" in detail or "тайный проход" in detail:
        keys = [h.key for h in m.holders()]
        lines.append(
            f"Допустимые anchors: {json.dumps(keys, ensure_ascii=False)}. "
            "Каждый ключ ровно один раз в части с нетайным путём от entry. "
            "Названия не являются ключами. У тайных частей required=false, без привязок."
        )
        if not keys:
            lines.append("Привязок нет: поле anchors не задавай ни в одной части.")
    if "лестниц" in detail or "разных уровнях" in detail:
        if intent is not None:
            by = {p.part_ref: p for p in intent.parts}
            previous = by[intent.entry]
            for part in intent.parts:
                if part.part_ref == intent.entry:
                    continue
                parent = by[part.connects_to] if part.connects_to else previous
                if part.passage_kind in {"stairs", "hatch"} and part.level == parent.level:
                    lines.append(
                        f"{part.part_ref} level={part.level} и родитель {parent.part_ref} level={parent.level}: "
                        "выбери door, arch, passage или gap, не stairs/hatch."
                    )
                previous = part
        lines.append("stairs/hatch допустимы только между разными level. Сохрани обязательные подземные части.")
    if "нет места на стороне" in detail or "не помещается рядом" in detail:
        lines.append(
            "approaches[].side должна оставаться свободной снаружи: перенеси соседнюю часть на другую side "
            "или выбери свободную сторону подхода. Для полос we нужны e/w, для ns — n/s. "
            "Если bands не нужны, можно убрать bands и ссылки band; обязательные подходы сохрани."
        )
    if "детал" in detail or ".cells" in detail:
        lines.append(
            "cells — [c0,r0,c1,r1] включительно, НЕ x,y,width,height; c1>=c0 и r1>=r0. "
            "Уменьши названную деталь до 1–2 клеток, например cells=[[1,1,1,1]], "
            "и перенеси внутрь пола, освободив клетки выходов. Не рисуй одной деталью рамку по периметру. "
            "При необходимости увеличь cols/rows части. Не убирай обязательные части."
        )
    if "detail_ref" in detail:
        lines.append(
            "Каждый detail_ref должен быть уникальным внутри своей части: переименуй повторы, например pillar_1/2."
        )
    if "коридор шире" in detail:
        lines.append(
            "shape=corridor требует min(cols,rows)<=2. Для широкого помещения выбери rect, "
            "для открытого участка — open; заданные в мандате формы сохрани."
        )
    if "шире одной клетки" in detail:
        lines.append("Для подхода door/passage задай width=1; широкий вход должен быть gate, arch, gap или edge.")
    lines.append("Исправь все перечисленные ошибки и вызови submit_layout с полным планом заново.")
    return "\n".join(lines)
