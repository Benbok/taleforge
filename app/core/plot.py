"""Каркас кампании: схема, выбор шаблона сюжета и проверки сервера (проект «Подготовка кампании», раздел 2).

Каркас — план, а не мир: он не создаёт записей в реестре. Локации, NPC и узлы — наброски со статусом
``sketch``; мастер разворачивает их инструментами, когда отряд до них доходит (раздел 3, следующая часть этапа).
"""

from __future__ import annotations

import re
from typing import Any

from app.core.brief import LENGTHS, PILLARS
from app.core.knowledge import terms

TOOL = "submit_campaign_plan"
ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
AMOUNT_WEIGHT = {"low": 0, "mid": 1, "high": 2}

# Сколько чего нужно по длительности: (мин, макс).
LIMITS: dict[str, dict[str, tuple[int, int]]] = {
    "oneshot": {"acts": (1, 1), "nodes": (3, 5), "locations": (2, 5), "npcs": (2, 6), "reveals": (1, 2)},
    "short": {"acts": (3, 3), "nodes": (2, 4), "locations": (4, 8), "npcs": (3, 8), "reveals": (2, 4)},
    "long": {"acts": (3, 4), "nodes": (3, 6), "locations": (6, 14), "npcs": (5, 14), "reveals": (3, 6)},
}
MIN_CLUES = 3
MIN_CLUE_PLACES = 2


def _str(desc: str, max_len: int = 600) -> dict:
    return {"type": "string", "description": desc, "maxLength": max_len}


def _id(desc: str) -> dict:
    return {"type": "string", "description": desc + " Латиница, цифры и _, до 32 знаков, например loc_harbor."}


def tool_spec() -> dict:
    """Инструмент, которым архитектор сдаёт каркас. Поля короткие: это наброски, детали появятся в игре."""
    person = {
        "id": _id("id внутри каркаса."),
        "name": _str("Имя.", 80),
        "template_id": {"type": "string", "description": "id шаблона существа из списка (creature....)."},
    }
    schema = {
        "type": "object",
        "properties": {
            "title": _str("Название кампании.", 80),
            "tagline": _str("Одна фраза-приманка без спойлеров.", 200),
            "tags": {"type": "array", "items": {"type": "string", "maxLength": 30}, "maxItems": 5},
            "public_intro": _str("Завязка для всех игроков: 1–2 абзаца, без тайн.", 1500),
            "structure_id": {"type": "string", "description": "id шаблона сюжета, на который опирался каркас."},
            "conflict": _str("Центральный конфликт."),
            "stakes": _str("Что будет с миром, если герои ничего не сделают."),
            "antagonists": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        **person,
                        "goal": _str("Цель."),
                        "methods": _str("Методы и ресурсы."),
                        "weakness": _str("Слабость."),
                        "secret": _str("Тайна."),
                        "threat": {
                            "type": "array",
                            "description": "План угрозы: 4–6 шагов, которые антагонист сделает, если его не остановят.",
                            "items": {"type": "string", "maxLength": 300},
                            "minItems": 4,
                            "maxItems": 6,
                        },
                    },
                    "required": ["id", "name", "goal", "methods", "weakness", "secret", "threat"],
                },
            },
            "locations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": _id("id внутри каркаса."),
                        "name": _str("Название.", 80),
                        "template_id": {"type": "string", "description": "id шаблона локации из списка."},
                        "lore_ref": {"type": "string", "description": "id записи лора пакета, если место из лора."},
                        "role": _str("Роль в сюжете, одна фраза.", 300),
                        "mood": _str("Атмосфера, одна-две фразы.", 300),
                        "secret": _str("Секрет места, одна фраза.", 300),
                    },
                    "required": ["id", "name", "role", "mood", "secret"],
                },
            },
            "npcs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        **person,
                        "role": _str("Роль в сюжете.", 300),
                        "want": _str("Чего хочет.", 300),
                        "fear": _str("Чего боится.", 300),
                        "secret": _str("Тайна.", 300),
                        "attitude": _str("Отношение к героям.", 200),
                        "look": _str("Внешность и манера, одной строкой.", 300),
                        "location_id": {"type": "string", "description": "Где его обычно найти: id локации каркаса."},
                    },
                    "required": ["id", "name", "template_id", "role", "want", "fear", "secret", "attitude", "look"],
                },
            },
            "factions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string", "description": "id фракции пакета, если она из лора."},
                        "name": _str("Название.", 80),
                        "stance": _str("Позиция в этом конфликте.", 300),
                    },
                    "required": ["name", "stance"],
                },
            },
            "acts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": _id("id акта."),
                        "title": _str("Название акта.", 80),
                        "goal": _str("Цель акта.", 300),
                        "exit": _str("Условие перехода к следующему акту.", 300),
                        "milestone_level": {
                            "type": "integer",
                            "description": "Уровень, который отряд получает в конце акта (веха), если он есть.",
                        },
                        "nodes": {
                            "type": "array",
                            "description": "Ключевые точки: событие, открытие или решение. Что происходит, а не "
                            "как игроки должны поступить.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": _id("id узла."),
                                    "title": _str("Название.", 80),
                                    "summary": _str("Что происходит.", 500),
                                    "location_id": {"type": "string", "description": "id локации каркаса."},
                                    "npc_ids": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["id", "title", "summary"],
                            },
                        },
                    },
                    "required": ["id", "title", "goal", "exit", "nodes"],
                },
            },
            "reveals": {
                "type": "array",
                "description": "Тайны, которые отряд может раскрыть. К каждой — не меньше трёх зацепок "
                "хотя бы в двух разных местах или у разных NPC, чтобы отряд не застрял.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": _id("id тайны."),
                        "truth": _str("Что раскрывается.", 500),
                        "node_id": {"type": "string", "description": "К какому узлу ведёт."},
                        "clues": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "at": {"type": "string", "description": "id локации или NPC каркаса."},
                                    "text": _str("Зацепка.", 300),
                                },
                                "required": ["at", "text"],
                            },
                        },
                    },
                    "required": ["id", "truth", "node_id", "clues"],
                },
            },
            "endings": {
                "type": "array",
                "description": "2–3 возможных финала: к чему может прийти история.",
                "items": {"type": "string", "maxLength": 400},
                "minItems": 2,
                "maxItems": 3,
            },
        },
        "required": [
            "title",
            "tagline",
            "public_intro",
            "conflict",
            "stakes",
            "antagonists",
            "locations",
            "npcs",
            "acts",
            "reveals",
            "endings",
        ],
    }
    return {
        "type": "function",
        "function": {"name": TOOL, "description": "Сдать каркас кампании на проверку сервера.", "parameters": schema},
    }


# --- выбор шаблона сюжета ---


def score_structure(entry_data: dict, brief: dict) -> float:
    pillars = entry_data.get("pillars") or {}
    wanted = brief.get("pillars") or {}
    score = sum(AMOUNT_WEIGHT[wanted.get(k, "mid")] * float(pillars.get(k, 0)) for k in PILLARS)
    emotions = set(brief.get("emotions") or [])
    score += 2 * len(emotions & set(entry_data.get("emotions") or []))
    return score


def pick_structure(structures: list, brief: dict, wanted_id: str | None = None):
    """Шаблон сюжета: заданный владельцем или лучший под анкету. При равенстве — по id, чтобы выбор был стабилен."""
    if wanted_id:
        return next((e for e in structures if e.id == wanted_id), None)
    if not structures:
        return None
    return sorted(structures, key=lambda e: (-score_structure(e.data, brief), e.id))[0]


# --- проверки сервера ---


def _banned(text: str, excluded: list[str]) -> list[str]:
    words = set(terms(text))
    hits = []
    for theme in excluded:
        stems = terms(theme)
        if stems and all(s in words for s in stems):
            hits.append(theme)
    return hits


def _flat_text(plan: dict) -> str:
    out: list[str] = []

    def walk(x: Any) -> None:
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            for k, v in x.items():
                if k not in ("id", "template_id", "lore_ref", "ref", "location_id", "node_id", "at", "npc_ids"):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(plan)
    return " ".join(out)


def check(
    raw: dict,
    *,
    length: str,
    catalog,
    excluded: list[str],
    level_cap: int = 20,
) -> tuple[dict | None, list[str]]:
    """Проверяет каркас. Возвращает (нормализованный каркас, []) или (None, ошибки по-русски для архитектора)."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["каркас должен быть объектом"]
    lim = LIMITS.get(length) or LIMITS["short"]
    plan = {k: raw.get(k) for k in tool_spec()["function"]["parameters"]["properties"]}
    for k in ("antagonists", "locations", "npcs", "factions", "acts", "reveals", "endings", "tags"):
        if not isinstance(plan.get(k), list):
            plan[k] = []
    for k in ("title", "tagline", "public_intro", "conflict", "stakes"):
        if not isinstance(plan.get(k), str) or not plan[k].strip():
            errors.append(f"нет поля {k}")

    seen: dict[str, str] = {}

    def reg(kind: str, obj: Any) -> str | None:
        if not isinstance(obj, dict):
            errors.append(f"{kind}: ожидается объект")
            return None
        oid = obj.get("id")
        if not isinstance(oid, str) or not ID.match(oid):
            errors.append(f"{kind}: неверный id {oid!r} (латиница, цифры и _, с буквы)")
            return None
        if oid in seen:
            errors.append(f"id {oid} повторяется ({seen[oid]} и {kind})")
            return None
        seen[oid] = kind
        return oid

    def template(kind_name: str, tid: Any, where: str, required: bool) -> None:
        if tid in (None, ""):
            if required:
                errors.append(f"{where}: нужен template_id ({kind_name})")
            return
        if catalog.find(str(tid), kind_name) is None:
            near = ", ".join(e.id for e in catalog.search(kind_name, str(tid).split(".")[-1], limit=3))
            errors.append(f"{where}: нет шаблона {tid}" + (f"; похожие: {near}" if near else ""))

    has_locations = bool(catalog.by_kind("location_template"))
    for a in plan["antagonists"]:
        oid = reg("антагонист", a)
        if oid:
            template("creature_template", a.get("template_id"), f"антагонист {oid}", False)
            if not 4 <= len(a.get("threat") or []) <= 6:
                errors.append(f"антагонист {oid}: план угрозы — от 4 до 6 шагов")
            a["threat_step"] = 0
    if not 1 <= len(plan["antagonists"]) <= 3:
        errors.append("антагонистов от 1 до 3")
    for loc in plan["locations"]:
        oid = reg("локация", loc)
        if oid:
            template("location_template", loc.get("template_id"), f"локация {oid}", has_locations)
            if loc.get("lore_ref") and catalog.find(str(loc["lore_ref"])) is None:
                errors.append(f"локация {oid}: нет записи лора {loc['lore_ref']}")
            loc["status"] = "sketch"
    for npc in plan["npcs"]:
        oid = reg("NPC", npc)
        if oid:
            template("creature_template", npc.get("template_id"), f"NPC {oid}", True)
            npc["status"] = "sketch"
    for f in plan["factions"]:
        if isinstance(f, dict) and f.get("ref") and catalog.find(str(f["ref"]), "faction") is None:
            errors.append(f"фракция {f.get('name')}: нет фракции {f['ref']} в пакете")

    loc_ids = {k for k, v in seen.items() if v == "локация"}
    npc_ids = {k for k, v in seen.items() if v == "NPC"}
    for npc in plan["npcs"]:
        if isinstance(npc, dict) and npc.get("location_id") and npc["location_id"] not in loc_ids:
            errors.append(f"NPC {npc.get('id')}: нет локации {npc['location_id']}")

    for key, ru in (("locations", "локаций"), ("npcs", "NPC")):
        lo, hi = lim[key]
        if not lo <= len(plan[key]) <= hi:
            errors.append(f"{ru} для длительности «{LENGTHS[length]}»: от {lo} до {hi}, сейчас {len(plan[key])}")
    lo, hi = lim["acts"]
    if not lo <= len(plan["acts"]) <= hi:
        errors.append(f"актов для длительности «{LENGTHS[length]}»: от {lo} до {hi}, сейчас {len(plan['acts'])}")
    node_ids: set[str] = set()
    for act in plan["acts"]:
        aid = reg("акт", act)
        if not aid:
            continue
        act["status"] = "pending"
        lvl = act.get("milestone_level")
        if lvl is not None and not (isinstance(lvl, int) and 2 <= lvl <= level_cap):
            errors.append(f"акт {aid}: веха уровня от 2 до {level_cap}")
        nodes = act.get("nodes") if isinstance(act.get("nodes"), list) else []
        act["nodes"] = nodes
        lo, hi = lim["nodes"]
        if not lo <= len(nodes) <= hi:
            errors.append(f"акт {aid}: узлов от {lo} до {hi}, сейчас {len(nodes)}")
        for n in nodes:
            nid = reg("узел", n)
            if not nid:
                continue
            node_ids.add(nid)
            n["status"] = "sketch"
            if n.get("location_id") and n["location_id"] not in loc_ids:
                errors.append(f"узел {nid}: нет локации {n['location_id']}")
            for x in n.get("npc_ids") or []:
                if x not in npc_ids and x not in {a.get("id") for a in plan["antagonists"] if isinstance(a, dict)}:
                    errors.append(f"узел {nid}: нет NPC {x}")
    if plan["acts"]:
        plan["acts"][0]["status"] = "active"

    lo, hi = lim["reveals"]
    if not lo <= len(plan["reveals"]) <= hi:
        errors.append(f"тайн от {lo} до {hi}, сейчас {len(plan['reveals'])}")
    places = loc_ids | npc_ids | {a.get("id") for a in plan["antagonists"] if isinstance(a, dict)}
    for r in plan["reveals"]:
        rid = reg("тайна", r)
        if not rid:
            continue
        r["revealed"] = False
        if r.get("node_id") not in node_ids:
            errors.append(f"тайна {rid}: нет узла {r.get('node_id')}")
        clues = [c for c in r.get("clues") or [] if isinstance(c, dict)]
        bad = [c.get("at") for c in clues if c.get("at") not in places]
        if bad:
            errors.append(f"тайна {rid}: зацепки ведут в неизвестные места {bad}")
        if len(clues) < MIN_CLUES or len({c.get("at") for c in clues}) < MIN_CLUE_PLACES:
            errors.append(f"тайна {rid}: нужно не меньше {MIN_CLUES} зацепок хотя бы в {MIN_CLUE_PLACES} разных местах")
    if not 2 <= len(plan["endings"]) <= 3:
        errors.append("финалов от 2 до 3")

    hits = _banned(_flat_text(plan), excluded)
    if hits:
        errors.append("в каркасе есть запретные темы: " + ", ".join(hits))
    plan["tags"] = [str(t)[:30] for t in plan["tags"]][:5]
    return (None, errors) if errors else (plan, [])


# --- ввод архитектора ---

SYSTEM = """Ты — архитектор кампании для текстовой ролевой игры по D&D 5e (SRD 5.1) на русском языке.
Твоя задача — каркас кампании: завязка, антагонисты с планом угрозы, акты и ключевые точки, наброски локаций
и NPC, тайны с зацепками и возможные финалы. Это наброски, а не детали: по одной-две фразы на пункт.
Детали мастер придумает, когда отряд до них дойдёт.

Правила:
- Строй каркас внутри мира пакета: места, фракции и факты бери из лора ниже, ссылайся на них через lore_ref и ref.
- NPC и антагонистов привязывай к шаблонам существ из списка (template_id), локации — к шаблонам локаций.
- Узлы описывают, что происходит, а не что должны сделать игроки. Решения игроков меняют исход, а не отменяют узел.
- К каждой тайне — не меньше трёх зацепок хотя бы в двух разных местах или у разных NPC.
- План угрозы антагониста — шаги, которые он сделает сам, если герои медлят.
- Завязка (public_intro), название, фраза-приманка и теги видны игрокам: в них не должно быть тайн.
- Запретные темы нельзя упоминать нигде.
Сдай каркас одним вызовом submit_campaign_plan."""


def plan_input(
    *,
    campaign_name: str,
    brief_text: str,
    length: str,
    difficulty: str,
    party: int,
    structure,
    excluded: list[str],
    lore: str,
    locations: list,
    npcs: list,
    note: str = "",
    previous: dict | None = None,
) -> str:
    lim = LIMITS.get(length) or LIMITS["short"]
    parts = [
        f"Кампания «{campaign_name}». Сложность: {difficulty}. Героев в отряде: {party}.",
        "Анкета владельца:\n" + (brief_text or "не заполнена: реши сам, сделай короткую кампанию."),
        f"Объём для длительности «{LENGTHS[length]}»: актов {lim['acts'][0]}–{lim['acts'][1]}, "
        f"узлов в акте {lim['nodes'][0]}–{lim['nodes'][1]}, локаций {lim['locations'][0]}–{lim['locations'][1]}, "
        f"NPC {lim['npcs'][0]}–{lim['npcs'][1]}, тайн {lim['reveals'][0]}–{lim['reveals'][1]}.",
    ]
    if structure is not None:
        beats = "\n".join(f"- {b}" for b in structure.data.get("beats") or [])
        parts.append(
            f"Шаблон сюжета ({structure.id}): {structure.name} — {structure.data.get('description', '')}\n"
            f"Опорные шаги (распредели по актам и узлам):\n{beats}"
        )
    if excluded:
        parts.append("Запретные темы: " + ", ".join(excluded))
    parts.append("Лор мира:\n" + (lore or "в пакете нет лора: опирайся на классическое фэнтези SRD."))
    if locations:
        parts.append("Шаблоны локаций: " + "; ".join(f"{e.id} ({e.name})" for e in locations))
    if npcs:
        parts.append("Шаблоны существ для NPC: " + "; ".join(f"{e.id} ({e.name})" for e in npcs))
    if previous:
        parts.append(
            "Предыдущий вариант каркаса (сделай новый, не повторяй его): "
            + f"{previous.get('title')} — {previous.get('tagline')}"
        )
    if note.strip():
        parts.append(f"Пожелание владельца к этому варианту: {note.strip()}")
    return "\n\n".join(parts)


def poster(plan: dict) -> dict:
    """Афиша для владельца и игроков: без спойлеров."""
    return {"title": plan.get("title"), "tagline": plan.get("tagline"), "tags": plan.get("tags") or []}


def render(plan: dict) -> str:
    """Каркас текстом для мастера: компактнее JSON и не рвётся при обрезке."""
    lines = [f"Каркас кампании «{plan.get('title')}». Конфликт: {plan.get('conflict')} Ставки: {plan.get('stakes')}"]
    for a in plan.get("antagonists") or []:
        steps = a.get("threat") or []
        step = int(a.get("threat_step") or 0)
        nxt = steps[step] if step < len(steps) else "план исполнен"
        lines.append(
            f"Антагонист {a.get('id')} {a.get('name')}: цель — {a.get('goal')}; методы — {a.get('methods')}; "
            f"слабость — {a.get('weakness')}; тайна — {a.get('secret')}. Следующий шаг угрозы: {nxt}"
        )
    for act in plan.get("acts") or []:
        lines.append(
            f"Акт {act.get('id')} «{act.get('title')}» [{act.get('status')}]: цель — {act.get('goal')}; "
            f"переход — {act.get('exit')}"
            + (f"; веха: уровень {act['milestone_level']}" if act.get("milestone_level") else "")
        )
        for n in act.get("nodes") or []:
            where = f" @{n['location_id']}" if n.get("location_id") else ""
            who = f" ({', '.join(n['npc_ids'])})" if n.get("npc_ids") else ""
            lines.append(f"  узел {n.get('id')} [{n.get('status')}] {n.get('title')}{where}{who}: {n.get('summary')}")
    lines.append("Локации (наброски):")
    for loc in plan.get("locations") or []:
        lines.append(
            f"- {loc.get('id')} {loc.get('name')} [{loc.get('status')}]: {loc.get('role')} {loc.get('mood')} "
            f"Секрет: {loc.get('secret')}"
        )
    lines.append("NPC (наброски):")
    for npc in plan.get("npcs") or []:
        lines.append(
            f"- {npc.get('id')} {npc.get('name')} [{npc.get('status')}]: {npc.get('role')}; хочет — {npc.get('want')}; "
            f"боится — {npc.get('fear')}; тайна — {npc.get('secret')}; к героям — {npc.get('attitude')}; "
            f"{npc.get('look')}"
        )
    for r in plan.get("reveals") or []:
        clues = "; ".join(f"{c.get('at')}: {c.get('text')}" for c in r.get("clues") or [])
        mark = "раскрыта" if r.get("revealed") else "не раскрыта"
        lines.append(f"Тайна {r.get('id')} ({mark}) → {r.get('node_id')}: {r.get('truth')} Зацепки: {clues}")
    if plan.get("endings"):
        lines.append("Возможные финалы: " + " | ".join(plan["endings"]))
    return "\n".join(lines)
