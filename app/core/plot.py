"""Каркас кампании: схема, выбор шаблона сюжета и проверки сервера (проект «Подготовка кампании», раздел 2).

Каркас — план, а не мир: он не создаёт записей в реестре. Локации, NPC и узлы — наброски со статусом
``sketch``; мастер разворачивает их инструментами, когда отряд до них доходит (раздел 3, следующая часть этапа).
"""

from __future__ import annotations

import copy
import re
import secrets
from datetime import UTC, datetime, timedelta
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
    # каркас готового приключения (app/core/modules.py): объём задаёт книга, а не анкета
    "module": {"acts": (1, 6), "nodes": (1, 12), "locations": (1, 40), "npcs": (0, 40), "reveals": (0, 12)},
}
MODULE = "module"
MIN_CLUES = 3
MIN_CLUE_PLACES = 2
CLUE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CONFISCATED_HINTS = (
    "лишённые оружия",
    "лишенные оружия",
    "отобрали оружие",
    "отняли оружие",
    "без оружия",
    "снаряжение изъято",
    "отняли снаряжение",
    "вещи изъяты",
    "вещи конфискованы",
    "отобрали снаряжение",
    "отобрали доспехи",
    "без снаряжения",
    "снаряжение отобрано",
    "изъяли оружие",
)


def new_clue_id() -> str:
    return f"clue_{secrets.token_hex(4)}"


def _str(desc: str, max_len: int = 600) -> dict:
    return {"type": "string", "description": desc, "maxLength": max_len}


def _id(desc: str) -> dict:
    return {"type": "string", "description": desc + " Латиница, цифры и _, до 32 знаков, например loc_harbor."}


def spatial_schema() -> dict:
    """Пространство места (спецификация 2026-10-12, §3.1): у каждого места каркаса, от поляны до храма."""
    part = {
        "type": "object",
        "properties": {
            "ref": _id("id части."),
            "name": _str("Название для героев, без тайн.", 80),
            "purpose": _str("Что здесь, одной фразой.", 300),
            "outdoor": {"type": "boolean", "description": "открытая местность"},
            "below": {"type": "boolean", "description": "уровнем ниже входа: подвал, крипта"},
            "secret": {"type": "boolean", "description": "за тайным проходом"},
            "required": {"type": "boolean", "description": "сюжетная цель: к ней ведёт открытый путь"},
            "lighting": {
                "type": "string",
                "enum": ["normal", "dim", "dark"],
                "description": "Необязательно: dim — намеренный полумрак, dark — неосвещённая сцена.",
            },
        },
        "required": ["ref", "name"],
    }
    approach = {
        "type": "object",
        "properties": {
            "name": _str("Как герои подходят.", 60),
            "kind": {"type": "string", "enum": ["road", "path", "door", "gate", "gap"]},
        },
        "required": ["name"],
    }
    return {
        "type": "object",
        "description": "Из чего состоит место: храм — из залов, поляна — из одной части. Без клеток и предметов — "
        "план построит сервер.",
        "properties": {
            "environment": {"type": "string", "enum": ["indoor", "outdoor", "mixed"]},
            "scale": {"type": "string", "enum": ["small", "medium", "large"]},
            "parts": {"type": "array", "minItems": 1, "maxItems": 6, "description": "Первая — вход.", "items": part},
            "approaches": {"type": "array", "minItems": 1, "maxItems": 3, "items": approach},
            "links": {"type": "array", "maxItems": 4, "items": {"type": "string"}, "description": "id мест рядом"},
        },
        "required": ["environment", "parts", "approaches"],
    }


def tool_spec() -> dict:
    """Инструмент, которым архитектор сдаёт каркас. Поля короткие: это наброски, детали появятся в игре."""
    person = {
        "id": _id("id внутри каркаса."),
        "name": _str("Имя.", 80),
        "template_id": {"type": "string", "description": "id шаблона существа из списка (creature....)."},
    }
    # Характер основных персонажей: мастер видит его, когда персонаж рядом, и ведёт его одинаково во всех играх.
    character = {
        "character": _str("Необязательно: характер в 2–3 чертах.", 200),
        "speech": _str("Необязательно: манера речи и пример фразы.", 300),
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
                        **character,
                        "on_meeting": _str("Необязательно: как ведёт себя при встрече с героями.", 300),
                        "if_foiled": _str("Необязательно: что сделает, если план сорвут.", 300),
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
                        "spatial": spatial_schema(),
                        "region": {"type": "string", "description": "id региона из regions, если регионы заданы."},
                    },
                    "required": ["id", "name", "role", "mood", "secret", "spatial"],
                },
            },
            "regions": {
                "type": "array",
                "maxItems": 8,
                "description": "Необязательно: крупные области мира, в которые входят локации. Иерархия без циклов.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": _id("id региона."),
                        "name": _str("Название региона.", 80),
                        "parent": {"type": "string", "description": "id родительского региона."},
                    },
                    "required": ["id", "name"],
                },
            },
            "routes": {
                "type": "array",
                "maxItems": 24,
                "description": "Необязательно: переходы между частями мест «loc_id/part_ref».",
                "items": {
                    "type": "object",
                    "properties": {
                        "ref": _id("id маршрута."),
                        "from": {"type": "string", "description": "Выход: loc_id/part_ref."},
                        "to": {"type": "string", "description": "Вход: loc_id/part_ref."},
                        "bidirectional": {"type": "boolean", "description": "Можно ли обратно; по умолчанию да."},
                        "hidden": {"type": "boolean", "description": "Тайный путь."},
                    },
                    "required": ["ref", "from", "to"],
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
                        **character,
                        "knows": _str("Необязательно: что знает — полезное героям и что скрывает.", 300),
                        "ties": _str("Необязательно: связи с другими NPC и фракциями.", 300),
                        "sways": _str("Необязательно: что расположит к героям и что оттолкнёт.", 300),
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
                                    "id": {
                                        "type": "string",
                                        "description": "id зацепки из каркаса: при пересмотре сохрани его; "
                                        "у новой зацепки не указывай, сервер выдаст сам.",
                                    },
                                    "at": {"type": "string", "description": "id локации или NPC каркаса."},
                                    "text": _str("Зацепка.", 300),
                                    "carrier": {
                                        "type": "object",
                                        "description": "Только если зацепку находят как вещь в месте (письмо, "
                                        "дневник, перстень): сервер положит её туда, когда место подготовят. "
                                        "Разговор или наблюдение носителя не имеют.",
                                        "properties": {
                                            "name": _str("Название вещи.", 80),
                                            "description": _str("Что видят герои, взяв вещь.", 400),
                                            "template_id": {
                                                "type": "string",
                                                "description": "шаблон предмета (item....), если у вещи есть "
                                                "механика; без него — записка без цены.",
                                            },
                                            "hidden": {
                                                "type": "boolean",
                                                "description": "лежит в контейнере места, а не на виду",
                                            },
                                        },
                                        "required": ["name", "description"],
                                    },
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
            "opening": {
                "type": "object",
                "description": "Стартовое условие кампании (снаряжение отряда). По умолчанию gear=kept.",
                "properties": {
                    "gear": {
                        "type": "string",
                        "enum": ["kept", "confiscated"],
                        "description": "kept — снаряжение при героях; confiscated — изъято и лежит в тайнике.",
                    },
                    "stash": {
                        "type": "string",
                        "description": "id локации каркаса, где сложены изъятые вещи (обязательно при confiscated).",
                    },
                    "note": _str("Одна фраза для мастера о стартовом положении.", 300),
                },
                "required": ["gear"],
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


WISH_WEIGHT, WISH_MAX = 1.5, 2


def score_structure(entry_data: dict, brief: dict) -> float:
    pillars = entry_data.get("pillars") or {}
    wanted = brief.get("pillars") or {}
    score = sum(AMOUNT_WEIGHT[wanted.get(k, "mid")] * float(pillars.get(k, 0)) for k in PILLARS)
    emotions = set(brief.get("emotions") or [])
    score += 2 * len(emotions & set(entry_data.get("emotions") or []))
    # свободные пожелания: слова из названия и описания шаблона («война на черте» → «Держать черту»)
    wishes = set(terms(brief.get("wishes") or ""))
    if wishes:
        words = set(terms(f"{entry_data.get('name', '')} {entry_data.get('description', '')}"))
        score += WISH_WEIGHT * min(len(wishes & words), WISH_MAX)
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
    keep_state: bool = False,
) -> tuple[dict | None, list[str]]:
    """Проверяет каркас. Возвращает (нормализованный каркас, []) или (None, ошибки по-русски для архитектора).

    ``keep_state`` — проверка каркаса, который уже идёт в игре (пересмотр между актами): статусы, шаги угроз и
    служебные поля сохраняются, а объём мест, NPC, актов и тайн не ограничивается — за игру их становится больше.
    """
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["каркас должен быть объектом"]
    lim = LIMITS.get(length) or LIMITS["short"]
    book = length == MODULE  # у книги своя мера: угроза короче, зацепок и финалов столько, сколько в ней есть
    props = tool_spec()["function"]["parameters"]["properties"]
    plan = copy.deepcopy(raw) if keep_state else {k: raw.get(k) for k in props}

    def state(obj: dict, key: str, value: Any) -> None:
        if keep_state:
            obj.setdefault(key, value)
        else:
            obj[key] = value

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

    clue_ids: set[str] = set()

    def clue_id(c: dict, rid: str) -> None:
        """Стабильный id зацепки: выдаётся один раз и хранится, не выводится из индекса или текста (§8.1)."""
        cid = c.get("id")
        if cid in (None, ""):
            cid = c["id"] = new_clue_id()
        if not isinstance(cid, str) or not CLUE_ID.match(cid):
            errors.append(f"тайна {rid}: неверный id зацепки {cid!r}")
        elif cid in clue_ids:
            errors.append(f"id зацепки {cid} повторяется")
        clue_ids.add(cid)

    def carrier(c: dict, rid: str) -> None:
        raw = c.get("carrier")
        if raw is None:
            c.pop("carrier", None)
            return
        name, desc = raw.get("name") if isinstance(raw, dict) else None, None
        if isinstance(raw, dict):
            desc = raw.get("description")
        if not isinstance(name, str) or not name.strip() or not isinstance(desc, str):
            errors.append(f"тайна {rid}: у носителя зацепки нужны name и description")
            return
        out = {"name": name.strip()[:80], "description": desc.strip()[:400], "hidden": bool(raw.get("hidden"))}
        if raw.get("template_id"):
            template("item_template", raw["template_id"], f"носитель зацепки тайны {rid}", False)
            out["template_id"] = str(raw["template_id"])
        c["carrier"] = out

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
            lo = 2 if book else 4
            if not lo <= len(a.get("threat") or []) <= 6:
                errors.append(f"антагонист {oid}: план угрозы — от {lo} до 6 шагов")
            state(a, "threat_step", 0)
    if not 1 <= len(plan["antagonists"]) <= 3:
        errors.append("антагонистов от 1 до 3")
    for loc in plan["locations"]:
        oid = reg("локация", loc)
        if oid:
            template("location_template", loc.get("template_id"), f"локация {oid}", has_locations)
            if loc.get("lore_ref") and catalog.find(str(loc["lore_ref"])) is None:
                errors.append(f"локация {oid}: нет записи лора {loc['lore_ref']}")
            if loc.get("spatial") is not None:
                from pydantic import ValidationError

                from app.core.layout.spatial import SpatialPlan

                try:
                    loc["spatial"] = SpatialPlan.model_validate(loc["spatial"]).model_dump(mode="json")
                except ValidationError as e:
                    why = "; ".join(f"{'.'.join(map(str, x['loc'])) or '-'}: {x['msg']}" for x in e.errors()[:3])
                    errors.append(f"локация {oid}: пространство — {why}")
            state(loc, "status", "sketch")
    for npc in plan["npcs"]:
        oid = reg("NPC", npc)
        if oid:
            template("creature_template", npc.get("template_id"), f"NPC {oid}", True)
            state(npc, "status", "sketch")
    for f in plan["factions"]:
        if isinstance(f, dict) and f.get("ref") and catalog.find(str(f["ref"]), "faction") is None:
            errors.append(f"фракция {f.get('name')}: нет фракции {f['ref']} в пакете")

    loc_ids = {k for k, v in seen.items() if v == "локация"}
    opening = plan.get("opening")
    if opening is not None:
        if not isinstance(opening, dict):
            errors.append("opening: ожидается объект")
            plan["opening"] = {"gear": "kept"}
        else:
            gear = opening.get("gear")
            if gear not in ("kept", "confiscated"):
                errors.append(f"opening.gear: ожидается 'kept' или 'confiscated', получено {gear!r}")
                gear = "kept"
            stash = opening.get("stash")
            if gear == "confiscated":
                if not stash or not isinstance(stash, str):
                    errors.append("opening: при gear=confiscated необходимо указать stash (id места каркаса)")
                elif stash not in loc_ids:
                    errors.append(f"opening.stash: место {stash} не найдено в локациях каркаса")
            norm_opening: dict[str, Any] = {"gear": gear}
            if stash and isinstance(stash, str):
                norm_opening["stash"] = stash
            if opening.get("note"):
                norm_opening["note"] = str(opening["note"])[:300].strip()
            if isinstance(opening.get("applied_to"), list):
                norm_opening["applied_to"] = [str(x) for x in opening["applied_to"]]
            plan["opening"] = norm_opening
    else:
        plan["opening"] = {"gear": "kept"}

    intro_text = (plan.get("public_intro") or "").lower()
    if plan["opening"].get("gear") != "confiscated" and any(hint in intro_text for hint in CONFISCATED_HINTS):
        errors.append(
            "завязка говорит об изъятом снаряжении, но opening.gear не установлен в confiscated со ссылкой на stash"
        )

    for loc in plan["locations"]:
        links = ((loc.get("spatial") or {}).get("links") or []) if isinstance(loc, dict) else []
        for link in links:
            if link not in loc_ids:
                errors.append(f"локация {loc.get('id')}: пространство — нет места {link}")
    if plan.get("regions") or plan.get("routes"):
        from app.core.geography.compiler import compile_plan
        from app.core.geography.contracts import GeographyError

        try:  # one geography validator for the architect, the author editor and publication
            compile_plan(plan)
        except GeographyError as e:
            errors.append(f"география: {e.code} ({', '.join(e.refs)})")
    npc_ids = {k for k, v in seen.items() if v == "NPC"}
    for npc in plan["npcs"]:
        if isinstance(npc, dict) and npc.get("location_id") and npc["location_id"] not in loc_ids:
            errors.append(f"NPC {npc.get('id')}: нет локации {npc['location_id']}")

    for key, ru in (("locations", "локаций"), ("npcs", "NPC")):
        lo, hi = lim[key]
        if not keep_state and not lo <= len(plan[key]) <= hi:
            errors.append(
                f"{ru} для длительности «{LENGTHS.get(length, length)}»: от {lo} до {hi}, сейчас {len(plan[key])}"
            )
    lo, hi = lim["acts"]
    if not keep_state and not lo <= len(plan["acts"]) <= hi:
        errors.append(
            f"актов для длительности «{LENGTHS.get(length, length)}»: от {lo} до {hi}, сейчас {len(plan['acts'])}"
        )
    node_ids: set[str] = set()
    for act in plan["acts"]:
        aid = reg("акт", act)
        if not aid:
            continue
        state(act, "status", "pending")
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
            state(n, "status", "sketch")
            if n.get("location_id") and n["location_id"] not in loc_ids:
                errors.append(f"узел {nid}: нет локации {n['location_id']}")
            for x in n.get("npc_ids") or []:
                if x not in npc_ids and x not in {a.get("id") for a in plan["antagonists"] if isinstance(a, dict)}:
                    errors.append(f"узел {nid}: нет NPC {x}")
    acts = [a for a in plan["acts"] if isinstance(a, dict)]
    if acts and not keep_state:
        acts[0]["status"] = "active"
    elif acts and not any(a.get("status") == "active" for a in acts):
        nxt = next((a for a in acts if a.get("status") == "pending"), None)
        if nxt is not None:
            nxt["status"] = "active"

    lo, hi = lim["reveals"]
    if not keep_state and not lo <= len(plan["reveals"]) <= hi:
        errors.append(f"тайн от {lo} до {hi}, сейчас {len(plan['reveals'])}")
    places = loc_ids | npc_ids | {a.get("id") for a in plan["antagonists"] if isinstance(a, dict)}
    for r in plan["reveals"]:
        rid = reg("тайна", r)
        if not rid:
            continue
        state(r, "revealed", False)
        if r.get("node_id") not in node_ids:
            errors.append(f"тайна {rid}: нет узла {r.get('node_id')}")
        clues = [c for c in r.get("clues") or [] if isinstance(c, dict)]
        r["clues"] = clues
        for c in clues:
            clue_id(c, rid)
            carrier(c, rid)
        bad = [c.get("at") for c in clues if c.get("at") not in places]
        if bad:
            errors.append(f"тайна {rid}: зацепки ведут в неизвестные места {bad}")
        if book:
            if not clues:
                errors.append(f"тайна {rid}: нужна хотя бы одна зацепка")
        elif len(clues) < MIN_CLUES or len({c.get("at") for c in clues}) < MIN_CLUE_PLACES:
            errors.append(f"тайна {rid}: нужно не меньше {MIN_CLUES} зацепок хотя бы в {MIN_CLUE_PLACES} разных местах")
    lo = 1 if book else 2
    if not lo <= len(plan["endings"]) <= 3:
        errors.append(f"финалов от {lo} до 3")

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
Для подробного мира можно задать regions (крупные области) и routes — переходы между конкретными частями мест
в виде «loc_id/part_ref»; part_ref берётся из spatial.parts этого места. Без них достаточно spatial.links.

Правила:
- Строй каркас внутри мира пакета: места, фракции и факты бери из лора ниже, ссылайся на них через lore_ref и ref.
- NPC и антагонистов привязывай к шаблонам существ из списка (template_id), локации — к шаблонам локаций.
- Ключевые лица и места мира — канон: не переименовывай их и не меняй их роль. Второстепенных NPC придумывай сам
  на шаблонах существ.
- Узлы описывают, что происходит, а не что должны сделать игроки. Решения игроков меняют исход, а не отменяют узел.
- К каждой тайне — не меньше трёх зацепок хотя бы в двух разных местах или у разных NPC.
- План угрозы антагониста — шаги, которые он сделает сам, если герои медлят.
- Завязка (public_intro), название, фраза-приманка и теги видны игрокам: в них не должно быть тайн.
- ???? ??????? ??????????, ??? ? ?????? ?????? ?????????? ??? ??????, ??????????? ????? opening:
  {gear: "confiscated", stash: "<id ????? ???????>", note: "..."}. ????? ???? ???????? ??? ??????.
- ? ??????? ????? ??????? spatial: ????? ?????? ???? ??? ??????. ??????? ????? (??????, ???????, ?????) ? scale
  small ? 1?2 ?????; ?????, ??????? ????????? ?? ?????? (????, ?????, ???????), ? ?? 6 ??????.
  ?????? ????? ? ????, ?????? ????? ? secret, ???????? ???? ? required, ?????? ? ?????? ? below.
  Без клеток и предметов; названия частей видны игрокам.
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
    figures: list[str] | None = None,
    places: list[str] | None = None,
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
    if places:
        parts.append("Ключевые места мира:\n" + "\n".join(places))
    if figures:
        parts.append(
            "Ключевые лица мира (template_id — их id; бери тех, кто подходит к анкете, а не всех):\n"
            + "\n".join(figures)
        )
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


def _short(text: Any, limit: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def place_line(e) -> str:
    """Ключевое место пакета одной строкой для архитектора."""
    return f"- {e.id} ({e.name}): {_short(e.data.get('description'), 200)}"


def figure_line(e, secret: str = "") -> str:
    """Ключевое лицо пакета одной строкой: кто, чего хочет, где, тайна (архитектор работает на стороне мастера)."""
    d = e.data
    bits = [_short(d.get("description"), 180)]
    if d.get("goal"):
        bits.append(f"хочет: {_short(d['goal'], 140)}")
    if d.get("location_ref"):
        bits.append(f"где: {d['location_ref']}")
    if secret:
        bits.append(f"тайна: {_short(secret, 220)}")
    return f"- {e.id} ({e.name}): " + "; ".join(b for b in bits if b)


def poster(plan: dict) -> dict:
    """Афиша для владельца и игроков: без спойлеров."""
    return {"title": plan.get("title"), "tagline": plan.get("tagline"), "tags": plan.get("tags") or []}


def clue_line(c: dict) -> str:
    head = f"[{c['id']}] " if c.get("id") else ""
    vessel = c.get("carrier") or {}
    thing = f" (вещь: {vessel.get('name')}{', спрятана' if vessel.get('hidden') else ''})" if vessel else ""
    return f"{head}{c.get('at')}: {c.get('text')}{thing}"


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
            + character_line(a)
            + (f" Уже сделано: {'; '.join(x['step'] for x in a['threat_log'])}." if a.get("threat_log") else "")
        )
    for act in plan.get("acts") or []:
        lines.append(
            f"Акт {act.get('id')} «{act.get('title')}» [{act.get('status')}]: цель — {act.get('goal')}; "
            f"переход — {act.get('exit')}"
            + (f"; веха: уровень {act['milestone_level']}" if act.get("milestone_level") else "")
            + (f"; итог — {act['outcome']}" if act.get("outcome") else "")
        )
        for n in act.get("nodes") or []:
            where = f" @{n['location_id']}" if n.get("location_id") else ""
            who = f" ({', '.join(n['npc_ids'])})" if n.get("npc_ids") else ""
            done = f" Итог — {n['outcome']}" if n.get("outcome") else ""
            lines.append(
                f"  узел {n.get('id')} [{n.get('status')}] {n.get('title')}{where}{who}: {n.get('summary')}{done}"
            )
    lines.append("Локации (наброски):")
    for loc in plan.get("locations") or []:
        lines.append(
            f"- {loc.get('id')} {loc.get('name')} [{loc.get('status')}]: {loc.get('role')} {loc.get('mood')} "
            f"Секрет: {loc.get('secret')}" + (f" Детали: {loc['details']}" if loc.get("details") else "")
        )
    lines.append("NPC (наброски):")
    for npc in plan.get("npcs") or []:
        lines.append(
            f"- {npc.get('id')} {npc.get('name')} [{npc.get('status')}]: {npc.get('role')}; хочет — {npc.get('want')}; "
            f"боится — {npc.get('fear')}; тайна — {npc.get('secret')}; к героям — {npc.get('attitude')}; "
            f"{npc.get('look')}" + character_line(npc) + (f" Детали: {npc['details']}" if npc.get("details") else "")
        )
    for r in plan.get("reveals") or []:
        clues = "; ".join(clue_line(c) for c in r.get("clues") or [])
        mark = f"раскрыта: {r.get('how')}" if r.get("revealed") else "не раскрыта"
        lines.append(f"Тайна {r.get('id')} ({mark}) → {r.get('node_id')}: {r.get('truth')} Зацепки: {clues}")
    if plan.get("endings"):
        lines.append("Возможные финалы: " + " | ".join(plan["endings"]))
    hooks = hooks_text(plan)
    if hooks:
        lines.append("Личные крючки героев:")
        lines += hooks
    return "\n".join(lines)


# --- каркас в игре (проект «Подготовка кампании», раздел 3) ---

CLOSED = ("done", "skipped")
# Раз во сколько игровых дней антагонисты сами делают шаг угрозы, если герои медлят. В ваншоте часы не идут.
THREAT_DAYS = {"oneshot": 0, "short": 3, "long": 5}
DAY = 24 * 3600


class PlotError(Exception):
    """Отказ операции над каркасом с причиной для мастера."""


def has_plan(plan: dict | None) -> bool:
    return bool(plan and plan.get("title"))


# Генерация дольше этого считается прерванной (сервер перезапустили посреди работы): её можно запустить заново
STALE = timedelta(minutes=15)


def status(settings: dict | None) -> tuple[str, str | None]:
    """(статус подготовки каркаса, ошибка) из settings кампании: none | generating | ready | failed."""
    st = (settings or {}).get("plan") or {}
    state, error = st.get("status") or "none", st.get("error")
    if state == "generating":
        try:
            since = datetime.fromisoformat(st.get("updated_at") or "")
        except ValueError:
            since = None
        if since is not None and datetime.now(UTC) - since > STALE:
            return "failed", "генерация прервалась, запустите её заново"
    return state, error


def active_act(plan: dict) -> dict | None:
    return next((a for a in plan.get("acts") or [] if a.get("status") == "active"), None)


def _index(plan: dict) -> dict[str, tuple[str, dict]]:
    out: dict[str, tuple[str, dict]] = {}
    for key, kind in (("antagonists", "antagonist"), ("locations", "location"), ("npcs", "npc"), ("reveals", "reveal")):
        for x in plan.get(key) or []:
            out[x["id"]] = (kind, x)
    for act in plan.get("acts") or []:
        out[act["id"]] = ("act", act)
        for n in act.get("nodes") or []:
            out[n["id"]] = ("node", n)
    return out


def node_act(plan: dict, node_id: str) -> dict | None:
    return next((a for a in plan.get("acts") or [] if any(n["id"] == node_id for n in a.get("nodes") or [])), None)


def valid_ids(plan: dict | None, kind: str) -> list[str]:
    """Допустимые id для инструментов мастера: открытые узлы, наброски, нераскрытые тайны, антагонисты."""
    if not has_plan(plan):
        return []
    if kind == "nodes":
        acts = [a for a in plan["acts"] if a.get("status") != "done"]
        return [n["id"] for a in acts for n in a["nodes"] if n.get("status") not in CLOSED]
    if kind == "sketches":
        return [x["id"] for k in ("locations", "npcs") for x in plan.get(k) or [] if x.get("status") == "sketch"]
    if kind == "reveals":
        return [r["id"] for r in plan.get("reveals") or [] if not r.get("revealed")]
    if kind == "antagonists":
        return [a["id"] for a in plan.get("antagonists") or []]
    if kind == "hooks":
        return hook_targets(plan)
    return []


def close_node(plan: dict, node_id: str, result: str, outcome: str) -> dict:
    kind, n = _index(plan).get(node_id, (None, None))
    if kind != "node":
        raise PlotError(f"нет узла {node_id}")
    if n.get("status") in CLOSED:
        raise PlotError(f"узел {node_id} уже закрыт: {n.get('outcome')}")
    act = node_act(plan, node_id)
    if act and act.get("status") == "done":
        raise PlotError(f"акт {act['id']} уже завершён")
    n["status"], n["outcome"] = result, outcome
    return n


def mark_revealed(plan: dict, reveal_id: str, how: str) -> dict:
    kind, r = _index(plan).get(reveal_id, (None, None))
    if kind != "reveal":
        raise PlotError(f"нет тайны {reveal_id}")
    if r.get("revealed"):
        raise PlotError(f"тайна {reveal_id} уже раскрыта")
    r["revealed"], r["how"] = True, how
    return r


def end_act(plan: dict, outcome: str) -> tuple[dict, dict | None]:
    """Закрывает текущий акт и открывает следующий. Незакрытые узлы остаются наброском: их можно не проходить."""
    act = active_act(plan)
    if act is None:
        raise PlotError("нет текущего акта: сюжет уже завершён")
    act["status"], act["outcome"] = "done", outcome
    nxt = next((a for a in plan["acts"] if a.get("status") == "pending"), None)
    if nxt is not None:
        nxt["status"] = "active"
    return act, nxt


def threat_step(plan: dict, antagonist_id: str, reason: str) -> tuple[dict, str, str | None]:
    """Антагонист делает следующий шаг плана. Возвращает (антагонист, сделанный шаг, следующий шаг или None)."""
    kind, a = _index(plan).get(antagonist_id, (None, None))
    if kind != "antagonist":
        raise PlotError(f"нет антагониста {antagonist_id}")
    steps, i = a.get("threat") or [], int(a.get("threat_step") or 0)
    if i >= len(steps):
        raise PlotError(f"план угрозы {a['name']} уже исполнен до конца")
    a["threat_step"] = i + 1
    a.setdefault("threat_log", []).append({"step": steps[i], "reason": reason})
    return a, steps[i], steps[i + 1] if i + 1 < len(steps) else None


def develop_sketch(plan: dict, sketch_id: str, details: str, entity_id: str | None) -> tuple[str, dict]:
    kind, x = _index(plan).get(sketch_id, (None, None))
    if kind not in ("location", "npc"):
        raise PlotError(f"нет наброска места или NPC {sketch_id}")
    if x.get("status") != "sketch":
        raise PlotError(f"{sketch_id} уже развёрнут")
    x["status"], x["details"] = "developed", details
    if entity_id:
        x["entity_id"] = entity_id
    return kind, x


HOOK_KINDS = ("node", "npc", "antagonist", "location")


def hook_targets(plan: dict | None) -> list[str]:
    """К чему можно привязать личный крючок героя: открытые узлы, NPC, злодеи и места каркаса."""
    if not has_plan(plan):
        return []
    idx = _index(plan)
    return [k for k, (kind, x) in idx.items() if kind in HOOK_KINDS and x.get("status") not in CLOSED]


def set_hook(plan: dict, character_id: str, name: str, ref: str, text: str) -> dict:
    """Личный крючок: тайная связь истории героя с узлом, NPC, злодеем или местом каркаса."""
    if ref not in hook_targets(plan):
        raise PlotError(f"нельзя привязать к {ref}: нужен открытый узел, NPC, злодей или место каркаса")
    hook = {"name": name, "ref": ref, "text": text}
    plan.setdefault("hooks", {})[character_id] = hook
    return hook


def hooks_text(plan: dict) -> list[str]:
    lines = [
        f"- {h.get('name')} ({cid}) → {h.get('ref')}: {h.get('text')}" for cid, h in (plan.get("hooks") or {}).items()
    ]
    lines += [
        f"- {cid}: {text}"
        for cid, text in (plan.get("character_links") or {}).items()
        if cid not in (plan.get("hooks") or {})
    ]
    return lines


def sketch_entity(plan: dict, sketch_id: str | None) -> str | None:
    if not sketch_id:
        return None
    x = _index(plan).get(sketch_id, (None, {}))[1]
    return x.get("entity_id")


def clock(plan: dict, game_time: int, length: str) -> list[tuple[dict, str, str | None]]:
    """Часы угроз: за каждые ``THREAT_DAYS`` игровых дней каждый антагонист делает шаг, если не остановлен.
    Первый вызов только запоминает точку отсчёта."""
    days = THREAT_DAYS.get(length, 0)
    if not days or not has_plan(plan):
        return []
    if "clock_at" not in plan:
        plan["clock_at"] = game_time
        return []
    periods = max(0, (game_time - int(plan["clock_at"])) // (days * DAY))
    out = []
    for _ in range(periods):
        plan["clock_at"] = int(plan["clock_at"]) + days * DAY
        for a in plan.get("antagonists") or []:
            if a.get("stopped") or int(a.get("threat_step") or 0) >= len(a.get("threat") or []):
                continue
            out.append(threat_step(plan, a["id"], f"прошло {days} дн. игрового времени"))
    return out


CHARACTER_FIELDS = (
    ("character", "характер"),
    ("speech", "речь"),
    ("knows", "знает"),
    ("ties", "связи"),
    ("sways", "отношение меняется"),
    ("on_meeting", "при встрече"),
    ("if_foiled", "если план сорвут"),
)


def character_line(x: dict) -> str:
    """Авторский характер персонажа; пусто, если автор его не задал — обычные игры не платят за лишний текст."""
    parts = [f"{label} — {x[key]}" for key, label in CHARACTER_FIELDS if str(x.get(key) or "").strip()]
    return (" Характер: " + "; ".join(parts) + ".") if parts else ""


def _sketch_line(x: dict, kind: str) -> str:
    if kind == "location":
        body = f"{x.get('role')} {x.get('mood')} Секрет: {x.get('secret')}"
    else:
        body = (
            f"{x.get('role')}; хочет — {x.get('want')}; боится — {x.get('fear')}; тайна — {x.get('secret')}; "
            f"к героям — {x.get('attitude')}; {x.get('look')}" + character_line(x)
        )
    if x.get("status") == "developed":
        ent = f", в реестре {x['entity_id']}" if x.get("entity_id") else ""
        return f"- {x['id']} {x.get('name')} [развёрнут{ent}]: {body} Детали: {x.get('details')}"
    return f"- {x['id']} {x.get('name')} [набросок]: {body}"


def now_block(plan: dict, *, location_entity_id: str | None = None) -> str:
    """«Сюжет сейчас»: текущий акт, его узлы и тайны, места и люди рядом, следующий шаг злодеев.
    Остальной каркас мастер читает инструментом get_plot."""
    acts = plan.get("acts") or []
    act = active_act(plan)
    lines = [f"Сюжет сейчас — «{plan.get('title')}». Конфликт: {plan.get('conflict')} Ставки: {plan.get('stakes')}"]
    opening = plan.get("opening") or {}
    if opening.get("gear") == "confiscated":
        stash = opening.get("stash")
        loc_name = next((loc.get("name") for loc in plan.get("locations") or [] if loc.get("id") == stash), stash)
        note = f" ({opening['note']})" if opening.get("note") else ""
        lines.append(f"Стартовое условие: снаряжение героев изъято и находится в «{loc_name}» (@{stash}){note}.")
    for a in acts:
        if a.get("status") == "done":
            lines.append(f"Пройден акт {a['id']} «{a.get('title')}»: {a.get('outcome')}")
    if act is None:
        lines.append("Все акты пройдены: веди к финалу. Возможные финалы: " + " | ".join(plan.get("endings") or []))
    else:
        num = acts.index(act) + 1
        lines.append(
            f"Текущий акт {num} из {len(acts)}: {act['id']} «{act.get('title')}». Цель — {act.get('goal')}; "
            f"переход — {act.get('exit')}"
            + (f"; веха: уровень {act['milestone_level']}" if act.get("milestone_level") else "")
        )
        for n in act.get("nodes") or []:
            where = f" @{n['location_id']}" if n.get("location_id") else ""
            who = f" ({', '.join(n['npc_ids'])})" if n.get("npc_ids") else ""
            if n.get("status") in CLOSED:
                mark = "пройден" if n["status"] == "done" else "обойдён"
                lines.append(f"  узел {n['id']} [{mark}] {n.get('title')}: итог — {n.get('outcome')}")
            else:
                lines.append(f"  узел {n['id']} [открыт] {n.get('title')}{where}{who}: {n.get('summary')}")
    node_ids = {n["id"] for n in (act or {}).get("nodes") or []}
    open_reveals = [r for r in plan.get("reveals") or [] if not r.get("revealed") and r.get("node_id") in node_ids]
    for r in open_reveals:
        clues = "; ".join(clue_line(c) for c in r.get("clues") or [])
        lines.append(f"Тайна {r['id']} → {r.get('node_id')} (не раскрыта): {r.get('truth')} Зацепки: {clues}")
    found = [r for r in plan.get("reveals") or [] if r.get("revealed")]
    if found:
        lines.append("Уже раскрыто: " + "; ".join(f"{r['id']} — {r.get('truth')}" for r in found))
    live_ids = {
        i for n in (act or {}).get("nodes") or [] if n.get("status") not in CLOSED for i in n.get("npc_ids") or []
    }
    for a in plan.get("antagonists") or []:
        steps, i = a.get("threat") or [], int(a.get("threat_step") or 0)
        nxt = f"следующий шаг угрозы ({i + 1}/{len(steps)}): {steps[i]}" if i < len(steps) else "план угрозы исполнен"
        done = f" Уже сделано: {'; '.join(steps[:i])}." if i else ""
        lines.append(
            f"Антагонист {a['id']} {a.get('name')}: цель — {a.get('goal')}; методы — {a.get('methods')}; "
            f"слабость — {a.get('weakness')}; {nxt}.{done}"
            + (character_line(a) if a.get("id") in live_ids else "")  # характер — только когда он в игре сейчас
        )
    # места и люди рядом: из открытых узлов акта, текущей локации сцены и NPC, которые там живут
    live = [n for n in (act or {}).get("nodes") or [] if n.get("status") not in CLOSED]
    near_loc = {n.get("location_id") for n in live}
    near_npc = {i for n in live for i in n.get("npc_ids") or []}
    here = None
    if location_entity_id:
        here = next((x for x in plan.get("locations") or [] if x.get("entity_id") == location_entity_id), None)
    if here is not None:
        near_loc.add(here["id"])
    near_npc |= {x["id"] for x in plan.get("npcs") or [] if x.get("location_id") in near_loc}
    locs = [x for x in plan.get("locations") or [] if x["id"] in near_loc]
    npcs = [x for x in plan.get("npcs") or [] if x["id"] in near_npc]
    if here is not None:
        lines.append(f"Отряд сейчас в месте каркаса {here['id']} {here.get('name')}.")
    if locs or npcs:
        lines.append("Места и люди рядом:")
        lines += [_sketch_line(x, "location") for x in locs] + [_sketch_line(x, "npc") for x in npcs]
    hooks = hooks_text(plan)
    if hooks:
        lines.append("Личные крючки героев (вплетай в сцены, прямо не раскрывай):")
        lines += hooks
    later = [a for a in acts if a.get("status") == "pending"]
    if later:
        lines.append("Дальше: " + "; ".join(f"«{a.get('title')}» — {a.get('goal')}" for a in later))
    if act is not None and plan.get("endings"):
        lines.append("Возможные финалы: " + " | ".join(plan["endings"]))
    return "\n".join(lines)


# --- пересмотр между актами ---

REVISE_TOOL = "submit_plan_revision"

REVISE_SYSTEM = """Ты — архитектор кампании для текстовой ролевой игры по D&D 5e (SRD 5.1) на русском языке.
Отряд только что закончил акт. Пересмотри оставшиеся акты с учётом того, что уже произошло: итогов узлов,
раскрытых тайн, шагов злодеев. Сохрани то, что ещё работает, поменяй то, что после решений игроков потеряло смысл,
и подхвати ниточки, которые игроки тянут сами. Это наброски: по одной-две фразы на пункт.

Правила:
- Верни все оставшиеся акты целиком (текущий и следующие), с узлами. Пройденные акты не трогай.
- Id узлов, на которые ссылаются нераскрытые тайны, сохрани, либо сдай эти тайны заново с новым node_id.
- Новые места, NPC и тайны — только если они нужны; id не должны повторять существующие.
- Запретные темы нельзя упоминать нигде.
Сдай пересмотр одним вызовом submit_plan_revision."""


def revision_spec() -> dict:
    props = tool_spec()["function"]["parameters"]["properties"]
    schema = {
        "type": "object",
        "properties": {
            "summary": _str("Что изменилось и почему, для владельца кампании: 1–3 фразы.", 600),
            "acts": {**props["acts"], "description": "Все оставшиеся акты: текущий и следующие."},
            "locations": {**props["locations"], "description": "Только новые места."},
            "npcs": {**props["npcs"], "description": "Только новые NPC."},
            "reveals": {**props["reveals"], "description": "Новые или переписанные тайны (тот же id — замена)."},
        },
        "required": ["summary", "acts"],
    }
    return {
        "type": "function",
        "function": {"name": REVISE_TOOL, "description": "Сдать пересмотр оставшихся актов.", "parameters": schema},
    }


def open_acts(plan: dict) -> list[dict]:
    """Акты, которые можно пересмотреть: следующие и текущий, если в нём ещё ничего не пройдено."""
    out = []
    for a in plan.get("acts") or []:
        if a.get("status") == "pending":
            out.append(a)
        elif a.get("status") == "active" and not any(n.get("status") in CLOSED for n in a.get("nodes") or []):
            out.append(a)
    return out


def merge_revision(plan: dict, raw: dict) -> tuple[dict, list[str]]:
    """Накладывает пересмотр на текущий каркас. Акт, в котором за время пересмотра что-то прошли, не меняется."""
    if not isinstance(raw, dict):
        return plan, ["пересмотр должен быть объектом"]
    new = copy.deepcopy(plan)
    replaceable = {a["id"] for a in open_acts(new)}
    kept = [a for a in new["acts"] if a["id"] not in replaceable]
    incoming = [a for a in raw.get("acts") or [] if isinstance(a, dict)]
    if not incoming:
        return plan, ["нужны оставшиеся акты"]
    was_active = next((a["id"] for a in new["acts"] if a.get("status") == "active"), None)
    fresh = []
    for a in incoming:
        a = copy.deepcopy(a)
        if a.get("id") in {k["id"] for k in kept}:
            continue  # этот акт уже нельзя переписать
        a.pop("status", None)
        for n in a.get("nodes") or []:
            if isinstance(n, dict):
                n.pop("status", None)
                n.pop("outcome", None)
        fresh.append(a)
    if was_active in replaceable and fresh:
        fresh[0]["status"] = "active"
    new["acts"] = kept + fresh
    for key in ("locations", "npcs"):
        new[key] = list(new.get(key) or []) + [copy.deepcopy(x) for x in raw.get(key) or [] if isinstance(x, dict)]
    by_id = {r["id"]: r for r in new.get("reveals") or []}
    for r in raw.get("reveals") or []:
        if not isinstance(r, dict):
            continue
        old = by_id.get(r.get("id"))
        if old is not None and old.get("revealed"):
            continue  # раскрытое уже не переписать
        r = copy.deepcopy(r)
        r.pop("revealed", None)
        by_id[r.get("id")] = r
    new["reveals"] = list(by_id.values())
    return new, []


def revise_input(plan: dict, *, brief_text: str, excluded: list[str]) -> str:
    parts = [
        "Анкета владельца:\n" + (brief_text or "не заполнена."),
        "Каркас с отметками прогресса:\n" + render(plan),
        "Можно переписать акты: " + ", ".join(a["id"] for a in open_acts(plan)),
    ]
    if excluded:
        parts.append("Запретные темы: " + ", ".join(excluded))
    return "\n\n".join(parts)


def check_adaptive_plan(plan: dict, *, catalog) -> tuple[dict | None, list[str]]:
    """Проверка целостности плана при адаптации в ходе игры без навязывания стартовых минимумов."""
    return check(plan, length=MODULE, catalog=catalog, excluded=[], keep_state=True)
