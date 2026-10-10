"""Готовые приключения: модуль из книги становится маленьким пакетом поверх SRD (design/adventure-modules.md).

Переводчик (app/agents/translator.py) сдаёт модуль одним вызовом инструмента: места с комнатами, существа и
предметы, которых нет в SRD, сюжетный каркас в схеме архитектора, зацепки и эпилог. Сервер собирает из этого
пакет ``module-<slug>`` во временной папке и проверяет его тем же загрузчиком, что и любой пакет, плюс своими
проверками комнат. Ошибки уходят модели на исправление. Админ смотрит итог и публикует модуль: пакет
записывается в БД, как загруженный архивом.
"""

from __future__ import annotations

import copy
import re
import shutil
import subprocess
import tempfile
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import BASE_PACK_ID, from_packs
from app.content.importer import import_pack
from app.content.loader import Pack, PackError, load_pack
from app.content.vocab import CUSTOM_OP, MODIFIER_OPS
from app.core import plot
from app.core.rolls import SKILL_RU
from app.rules.dnd5e.tables import ABILITIES, SKILLS

TOOL = "submit_adventure_module"
MAP_TOOL = "submit_map_marks"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
LOCAL_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
RECORD_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
NUMBER = re.compile(r"^[0-9A-Za-zА-Яа-я]{1,4}$")
ITEM_CATEGORIES = ("weapon", "armor", "consumable", "gear", "tool", "treasure", "quest")
RARITIES = ("common", "uncommon", "rare", "very_rare", "legendary", "artifact")
# Что модуль может поменять у существа SRD. Действия (атаки, мультиатака) движок читает в строгом виде:
# их изменения — словами в book_note, числа атак остаются от основы.
CREATURE_CHANGES = {
    "hp",
    "ac",
    "ac_note",
    "speed",
    "abilities",
    "saves",
    "skills",
    "senses",
    "languages",
    "alignment",
    "size",
    "cr",
    "xp",
    "damage_resistances",
    "damage_immunities",
    "damage_vulnerabilities",
    "condition_immunities",
    "traits",
}
MAX_TEXT = 400_000  # знаков текста книги: около 150 страниц
MAX_ERRORS = 40
MAP_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
MAX_MAP = 15 * 1024 * 1024
MAX_PDF = 50 * 1024 * 1024


class ModuleError(Exception):
    """Модуль не принят: причина для админа."""


# --- текст книги ---


def extract_text(pdf: Path) -> tuple[str, int]:
    """Текст PDF и число страниц. pdftotext (poppler-utils) держит порядок колонок лучше библиотек на Python."""
    exe = shutil.which("pdftotext")
    if exe is None:
        raise ModuleError("на сервере нет pdftotext: установите пакет poppler-utils")
    try:
        out = subprocess.run([exe, "-enc", "UTF-8", str(pdf), "-"], capture_output=True, timeout=120, check=False)
    except subprocess.TimeoutExpired as e:
        raise ModuleError("pdftotext не справился за 2 минуты") from e
    if out.returncode != 0:
        raise ModuleError("PDF не читается: " + out.stderr.decode("utf-8", "replace").strip()[:300])
    text = out.stdout.decode("utf-8", "replace")
    pages = text.count("\f") or 1
    text = re.sub(r"[ \t]+\n", "\n", text.replace("\f", "\n\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 200:
        raise ModuleError("в PDF почти нет текста: похоже, это скан без текстового слоя")
    if len(text) > MAX_TEXT:
        raise ModuleError(f"книга слишком большая: {len(text)} знаков, предел {MAX_TEXT}")
    return text, pages


# --- SRD для переводчика и проверок ---


@cache
def srd(packs_root: Path) -> Pack:
    """Базовый пакет правил с диска. Он меняется только с версией сервера, поэтому загружается один раз."""
    pack, report = load_pack(packs_root / BASE_PACK_ID)
    if not report.ok:
        raise ModuleError("базовый пакет SRD не проходит проверку: " + "; ".join(report.errors[:3]))
    return pack


def srd_lists(base: Pack) -> str:
    """Существа, предметы и места SRD строками для задания переводчику."""
    by_kind: dict[str, list[str]] = {}
    for r in base.records.values():
        d = r.data
        if r.kind == "creature_template":
            ref = (d.get("srd_ref") or {}).get("name", "")
            line = f"{r.id} ({d.get('name')}, {ref}, ОП {d.get('cr')}, хиты {(d.get('hp') or {}).get('average')})"
        elif r.kind in ("item_template", "location_template"):
            line = f"{r.id} ({d.get('name')})"
        else:
            continue
        by_kind.setdefault(r.kind, []).append(line)
    return "\n\n".join(
        [
            "Существа SRD: " + "; ".join(sorted(by_kind.get("creature_template", []))),
            "Предметы SRD: " + "; ".join(sorted(by_kind.get("item_template", []))),
            "Шаблоны мест SRD: " + "; ".join(sorted(by_kind.get("location_template", []))),
        ]
    )


# --- инструмент переводчика ---


def _str(desc: str, max_len: int = 600) -> dict:
    return {"type": "string", "description": desc, "maxLength": max_len}


def _arr(items: dict, desc: str = "") -> dict:
    out: dict[str, Any] = {"type": "array", "items": items}
    if desc:
        out["description"] = desc
    return out


def _obj(props: dict, required: list[str], desc: str = "") -> dict:
    out: dict[str, Any] = {"type": "object", "properties": props, "required": required}
    if desc:
        out["description"] = desc
    return out


def _plot_schema() -> dict:
    """Каркас архитектора (app/core/plot.py) с мерой книги: угроза от 2 шагов, финалов от одного."""
    schema = copy.deepcopy(plot.tool_spec()["function"]["parameters"])
    props = schema["properties"]
    props["antagonists"]["items"]["properties"]["threat"]["minItems"] = 2
    props["endings"]["minItems"] = 1
    props["public_intro"]["description"] = "Завязка для всех игроков без тайн: что известно героям в начале."
    props["locations"]["items"]["properties"]["template_id"]["description"] = (
        "id места модуля (location....) из locations этого вызова или шаблона места SRD."
    )
    props["acts"]["items"]["properties"]["milestone_level"]["description"] = (
        "Уровень, который отряд получает в конце акта, как сказано в книге (опыт по этапам)."
    )
    props.pop("structure_id", None)
    return schema


def _ints(keys) -> dict:
    return {"type": "object", "properties": {k: {"type": "integer"} for k in keys}}


def _changes_schema() -> dict:
    """Что модуль меняет у существа SRD (CREATURE_CHANGES). Свойства перечислены: Gemini не берёт пустой object."""
    names = {"type": "array", "items": {"type": "string"}}
    props = {
        "hp": _obj({"average": {"type": "integer"}, "dice": {"type": "string"}}, ["average"]),
        "ac": {"type": "integer"},
        "ac_note": {"type": "string"},
        "speed": _ints(["walk", "fly", "swim", "climb", "burrow"]),
        "abilities": _ints(ABILITIES),
        "saves": _ints(ABILITIES),
        "skills": _ints(sorted(SKILLS)),
        "senses": _ints(["darkvision", "blindsight", "tremorsense", "truesight", "passive_perception"]),
        "languages": {"type": "string"},
        "alignment": {"type": "string"},
        "size": {"type": "string", "enum": ["tiny", "small", "medium", "large", "huge", "gargantuan"]},
        "cr": {"type": "number"},
        "xp": {"type": "integer"},
        "damage_resistances": names,
        "damage_immunities": names,
        "damage_vulnerabilities": names,
        "condition_immunities": names,
        "traits": _arr(_obj({"name": _str("Название.", 80), "description": _str("Правило.", 800)}, ["name"])),
    }
    return {"type": "object", "properties": props, "description": "Что отличается от основы, по книге."}


def tool_spec() -> dict:
    room = _obj(
        {
            "id": _str("id комнаты внутри места: латиница, цифры и _, например r1 или gate.", 32),
            "number": _str("Номер комнаты на карте, как в книге: 1, 2, 12. Пусто, если на карте номера нет.", 4),
            "name": _str("Название комнаты.", 80),
            "read_aloud": _str("Текст для чтения вслух из книги, если он есть, дословно.", 2000),
            "scenery": _str(
                "Только устойчивые, открыто видимые детали обстановки: архитектура, стены, пол, неподвижные "
                "предметы. Без существ, запланированных встреч, событий, секретов и возможной добычи.",
                1500,
            ),
            "description": _str("Что здесь есть и что происходит, по книге.", 2000),
            "checks": _arr(
                _obj(
                    {
                        "skill": {"type": "string", "enum": sorted(SKILLS)},
                        "ability": {"type": "string", "enum": list(ABILITIES), "description": "Без навыка."},
                        "save": {"type": "boolean", "description": "Это спасбросок, а не проверка."},
                        "dc": {"type": "integer", "description": "Сложность из книги."},
                        "text": _str("Когда бросать и что даёт успех или провал.", 400),
                    },
                    ["dc", "text"],
                ),
                "Проверки и спасброски комнаты со сложностью из книги.",
            ),
            "encounters": _arr(
                _obj(
                    {
                        "creature_ref": {"type": "string", "description": "id существа: SRD или из creatures."},
                        "count": {"type": "integer"},
                        "note": _str("Тактика, поведение, особые условия.", 400),
                    },
                    ["creature_ref", "count"],
                ),
            ),
            "treasure": _arr(
                _obj(
                    {
                        "item_ref": {"type": "string", "description": "id предмета, если это предмет."},
                        "text": _str("Что найдут: монеты, вещи, где лежит.", 300),
                    },
                    ["text"],
                ),
            ),
            "secrets": _arr(_str("Ловушка, тайник, скрытая дверь.", 400)),
            "exits": _arr({"type": "string"}, "id комнат этого же места, куда отсюда можно пройти."),
        },
        ["id", "name", "description"],
    )
    location = _obj(
        {
            "id": _str("id записи места: location.<латиница>, например location.davos_crypt.", 60),
            "name": _str("Название.", 80),
            "description": _str("Общее описание места.", 1500),
            "features": _arr(_str("Общая особенность: потолки, двери, свет.", 300)),
            "rooms": _arr(room, "Комнаты и зоны места в порядке книги."),
        },
        ["id", "name", "description", "rooms"],
    )
    creature = _obj(
        {
            "id": _str("id: creature.<латиница>. Не совпадает с id SRD.", 60),
            "name": _str("Имя по книге.", 80),
            "base_ref": {"type": "string", "description": "id существа SRD, чьи характеристики берутся за основу."},
            "description": _str("Кто это и как выглядит.", 1000),
            "changes": _changes_schema(),
            "book_note": _str("Чем существо расходится с книгой, если движок не умеет её правило.", 600),
        },
        ["id", "name", "base_ref", "description"],
    )
    item = _obj(
        {
            "id": _str("id: item.<латиница>. Не совпадает с id SRD.", 60),
            "name": _str("Название по книге.", 80),
            "base_ref": {"type": "string", "description": "id предмета SRD за основу, если есть похожий."},
            "category": {"type": "string", "enum": list(ITEM_CATEGORIES)},
            "rarity": {"type": "string", "enum": list(RARITIES)},
            "price_gp": {"type": "number", "description": "Цена в зм по книге, если указана."},
            "description": _str("Что это и что делает, по книге.", 1000),
            "modifiers": _arr(
                _obj(
                    {
                        "op": {"type": "string", "enum": sorted(MODIFIER_OPS - {CUSTOM_OP})},
                        "target": {"type": "string", "description": "Что меняется: ac, attack, damage, check, save."},
                        "stat": {"type": "string", "description": "Для resource: hp и другие запасы."},
                        "value": {"type": "number"},
                        "delta": {"type": "string", "description": "Кубики или число: '2d4+2'."},
                        "condition": {"type": "string", "description": "Состояние SRD: poisoned, frightened."},
                        "damage_type": {"type": "string"},
                        "skill": {"type": "string"},
                        "when": {"type": "string", "description": "Когда действует, коротко латиницей."},
                        "text": _str("Правило словами для мастера.", 300),
                    },
                    ["op"],
                ),
                "Механика словарём движка, например {op: resource, stat: hp, delta: '2d4+2'} или "
                "{op: add, target: ac, value: 1}. Если правило книги не выражается — ближайший вариант и book_note.",
            ),
            "book_note": _str("Чем предмет расходится с книгой.", 600),
        },
        ["id", "name", "category", "description"],
    )
    schema = _obj(
        {
            "title": _str("Название приключения по-русски.", 120),
            "slug": _str("Короткое имя латиницей через дефис, например unquiet-dead.", 40),
            "summary": _str("О чём приключение в 2–3 фразах для библиотеки, без тайн.", 600),
            "levels": _obj(
                {"start": {"type": "integer"}, "end": {"type": "integer"}},
                ["start", "end"],
                "Уровни героев: с какого начинают и до какого дорастут.",
            ),
            "party_size": {"type": "integer", "description": "На сколько героев рассчитано."},
            "credits": _str("Автор и издатель, как указано в книге.", 300),
            "hooks": _arr(
                _obj(
                    {"id": _str("id зацепки.", 32), "title": _str("Название.", 80), "text": _str("Текст.", 800)},
                    [
                        "id",
                        "title",
                        "text",
                    ],
                ),
                "Сюжетные зацепки из книги: как герои попадают в историю.",
            ),
            "locations": _arr(location),
            "creatures": _arr(creature, "Существа книги, которых нет в SRD или которые в ней изменены."),
            "items": _arr(item, "Предметы книги, которых нет в SRD."),
            "plot": _plot_schema(),
            "epilogue": _str("Чем кончается приключение и какие награды обещаны.", 1500),
            "notes": _arr(
                _str("Пометка для админа.", 400),
                "Что ты придумал сам, чего не было в книге, и где пришлось отступить от неё.",
            ),
        },
        ["title", "slug", "summary", "levels", "hooks", "locations", "plot"],
    )
    return {
        "type": "function",
        "function": {
            "name": TOOL,
            "description": "Сдать разобранное приключение на проверку сервера.",
            "parameters": schema,
        },
    }


SYSTEM = """Ты — переводчик готовых приключений D&D 5e в формат текстовой ролевой игры с ИИ-мастером.
Тебе дают текст опубликованного приключения. Разбери его без пересказа своими словами: тексты для чтения вслух,
сложности проверок, состав столкновений и сокровища переноси так, как они в книге.

Правила:
- Играем в мире самой книги на правилах SRD 5.1. Не добавляй лишних мест и событий.
- Места: каждое место книги (кладбище, склеп, храм) — запись location.* с комнатами. Номер комнаты — как на карте
  книги. Выходы комнаты — id комнат этого же места.
- Для каждой комнаты отдельно укажи scenery: только неизменную видимую обстановку без существ, возможных встреч,
  добычи, секретов и событий. Даже если в read_aloud сказано «два скелета бродят», скелеты относятся к encounters,
  а scenery содержит только стены, гробы, свет и иные устойчивые детали. read_aloud и description книги не изменяй.
- Существа: если в книге существо SRD без изменений, ссылайся на его id из списка. Если изменено или его нет в SRD —
  опиши его в creatures на основе ближайшего существа SRD (base_ref) и запиши отличия в changes.
- Предметы: если предмета нет в SRD, опиши его в items. Механику пиши только словарём движка (modifiers). Если
  правило книги словарь не выражает, возьми ближайший вариант и напиши в book_note, чем он отличается.
- Если в книге чего-то не хватает, придумай сам в духе книги и отметь это в notes.
- Каркас (plot) — в схеме архитектора: антагонисты с планом угрозы, места каркаса со ссылкой template_id на места
  модуля, NPC на шаблонах существ, акты с узлами, тайны с зацепками, финалы. Уровни по этапам книги — в
  milestone_level актов.
- Названия и тексты — по-русски.
Сдай приключение одним вызовом submit_adventure_module."""


def translator_input(text: str, base: Pack, note: str = "") -> str:
    parts = [
        "Навыки (skill): " + ", ".join(f"{k} ({SKILL_RU.get(k, k)})" for k in sorted(SKILLS)),
        srd_lists(base),
    ]
    if note.strip():
        parts.append("Пожелание админа к разбору: " + note.strip())
    parts.append("Текст приключения:\n\n" + text)
    return "\n\n".join(parts)


# --- сборка пакета ---


def _slug_id(slug: str) -> str:
    return slug.replace("-", "_")


def _clean_rooms(rooms: Any) -> list[dict]:
    out = []
    for r in rooms if isinstance(rooms, list) else []:
        if not isinstance(r, dict):
            continue
        room = {
            k: r[k]
            for k in ("id", "number", "name", "read_aloud", "description", "scenery")
            if r.get(k) not in (None, "")
        }
        if room.get("number") is not None:
            room["number"] = str(room["number"]).strip()
        for k in ("checks", "encounters", "treasure", "secrets", "exits"):
            v = r.get(k)
            if isinstance(v, list) and v:
                room[k] = copy.deepcopy(v)
        out.append(room)
    return out


def build_records(raw: dict, base: Pack) -> tuple[dict[str, list[dict]], list[str]]:
    """Записи пакета модуля по сдаче переводчика: места, существа, предметы. Каркас — отдельно (adventure)."""
    errors: list[str] = []
    out: dict[str, list[dict]] = {"location_template": [], "creature_template": [], "item_template": []}
    tags = ["module"]

    for loc in raw.get("locations") or []:
        if not isinstance(loc, dict):
            errors.append("место: ожидается объект")
            continue
        rec = {
            "id": loc.get("id"),
            "name": loc.get("name"),
            "status": "canon",
            "tags": tags,
            "description": loc.get("description") or "",
            "rooms": _clean_rooms(loc.get("rooms")),
        }
        if isinstance(loc.get("features"), list) and loc["features"]:
            rec["features"] = [str(x) for x in loc["features"]]
        out["location_template"].append(rec)

    for cr in raw.get("creatures") or []:
        if not isinstance(cr, dict):
            errors.append("существо: ожидается объект")
            continue
        cid = cr.get("id")
        b = base.records.get(str(cr.get("base_ref") or ""))
        if b is None or b.kind != "creature_template":
            errors.append(f"существо {cid}: base_ref {cr.get('base_ref')!r} — нет такого существа SRD")
            continue
        changes = cr.get("changes") if isinstance(cr.get("changes"), dict) else {}
        extra = sorted(set(changes) - CREATURE_CHANGES)
        if extra:
            allowed = ", ".join(sorted(CREATURE_CHANGES))
            errors.append(f"существо {cid}: в changes нельзя менять {', '.join(extra)} (только {allowed})")
        hp = changes.get("hp")
        if hp is not None and not (isinstance(hp, dict) and isinstance(hp.get("average"), int) and hp["average"] > 0):
            errors.append(f"существо {cid}: hp — объект {{average: число, dice: '6d8'}}")
        ac = changes.get("ac")
        if ac is not None and not (isinstance(ac, int) and 1 <= ac <= 30):
            errors.append(f"существо {cid}: ac — целое от 1 до 30")
        rec = {
            "id": cid,
            "name": cr.get("name"),
            "status": "canon",
            "tags": tags,
            "description": cr.get("description") or "",
            "srd_ref": dict(b.data["srd_ref"]),
            "base_ref": b.id,
            "cr": b.data.get("cr"),
            **{k: copy.deepcopy(v) for k, v in changes.items() if k in CREATURE_CHANGES},
        }
        if cr.get("book_note"):
            rec["book_note"] = str(cr["book_note"])
        out["creature_template"].append(rec)

    for it in raw.get("items") or []:
        if not isinstance(it, dict):
            errors.append("предмет: ожидается объект")
            continue
        iid = it.get("id")
        rec: dict[str, Any] = {
            "id": iid,
            "name": it.get("name"),
            "status": "canon",
            "tags": tags,
            "description": it.get("description") or "",
        }
        b = None
        if it.get("base_ref"):
            b = base.records.get(str(it["base_ref"]))
            if b is None or b.kind != "item_template":
                errors.append(f"предмет {iid}: base_ref {it['base_ref']!r} — нет такого предмета SRD")
                continue
            rec["base_ref"] = b.id
            if isinstance(b.data.get("srd_ref"), dict):
                rec["srd_ref"] = dict(b.data["srd_ref"])
        category = it.get("category") or (b.data.get("category") if b else None)
        if category not in ITEM_CATEGORIES:
            errors.append(f"предмет {iid}: category одна из {', '.join(ITEM_CATEGORIES)}")
        rec["category"] = category
        if it.get("rarity"):
            if it["rarity"] not in RARITIES:
                errors.append(f"предмет {iid}: rarity одна из {', '.join(RARITIES)}")
            rec["rarity"] = it["rarity"]
        price = it.get("price_gp")
        rec["price"] = {"gp": price} if isinstance(price, int | float) else (b.data.get("price") if b else {"gp": 0})
        if isinstance(it.get("modifiers"), list) and it["modifiers"]:
            rec["modifiers"] = copy.deepcopy(it["modifiers"])
        if it.get("book_note"):
            rec["book_note"] = str(it["book_note"])
        out["item_template"].append(rec)
    return out, errors


def adventure_record(raw: dict, plan: dict, maps: list[dict] | None = None, module_id: str = "") -> dict:
    """Запись приключения: каркас, зацепки, эпилог, уровни и карты мест. Картинки карт лежат в папке модуля
    ``module_id`` (app/api/modules.py)."""
    levels = raw.get("levels") if isinstance(raw.get("levels"), dict) else {}
    rec = {
        "id": f"adventure.{_slug_id(raw['slug'])}",
        "name": raw.get("title"),
        "status": "canon",
        "tags": ["module"],
        "description": raw.get("summary") or "",
        "levels": {"start": levels.get("start"), "end": levels.get("end")},
        "party_size": raw.get("party_size"),
        "credits": raw.get("credits") or "",
        "xp": "milestone",
        "hooks": copy.deepcopy(raw.get("hooks") or []),
        "plot": plan,
        "epilogue": raw.get("epilogue") or "",
        "module_id": module_id,
    }
    if maps:
        rec["maps"] = [
            {
                "id": m["id"],
                "file": m["file"],
                "location_ref": m["location_id"],
                "grid": m.get("grid"),
                "marks": m.get("marks") or [],
            }
            for m in maps
            if m.get("location_id")
        ]
    return rec


def write_pack(dest: Path, slug: str, version: str, title: str, records: dict[str, list[dict]]) -> Path:
    """Папка пакета модуля: pack.yaml и data/<вид>.yaml. Ровно то, что загрузил бы админ архивом."""
    root = dest / f"module-{slug}"
    (root / "data").mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": f"module-{slug}",
        "name": title,
        "version": version,
        "ruleset": "dnd5e",
        "ruleset_base": "srd-5.1",
        "depends": {BASE_PACK_ID: "*"},
        "kind": "module",
        "languages": ["ru"],
    }
    _dump(root / "pack.yaml", manifest)
    files = {
        "location_template": "locations",
        "creature_template": "creatures",
        "item_template": "items",
        "adventure": "adventure",
    }
    for kind, name in files.items():
        if records.get(kind):
            _dump(root / "data" / f"{name}.yaml", {"kind": kind, "items": records[kind]})
    return root


def _dump(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")


# --- проверки ---


def _check_rooms(records: dict[str, list[dict]], catalog, errors: list[str]) -> None:
    for loc in records["location_template"]:
        lid = loc.get("id")
        rooms = loc.get("rooms") or []
        if not rooms:
            errors.append(f"место {lid}: нет комнат")
        ids: set[str] = set()
        numbers: set[str] = set()
        for r in rooms:
            rid = r.get("id")
            where = f"место {lid}, комната {rid}"
            if not isinstance(rid, str) or not LOCAL_ID.match(rid):
                errors.append(f"место {lid}: неверный id комнаты {rid!r} (латиница, цифры и _, с буквы)")
                continue
            if rid in ids:
                errors.append(f"место {lid}: комната {rid} повторяется")
            ids.add(rid)
            n = r.get("number")
            if n is not None:
                if not NUMBER.match(n):
                    errors.append(f"{where}: номер {n!r} — как на карте, до 4 знаков")
                elif n in numbers:
                    errors.append(f"место {lid}: номер {n} у двух комнат")
                numbers.add(n)
            for c in r.get("checks") or []:
                if not isinstance(c, dict):
                    errors.append(f"{where}: проверка — объект")
                    continue
                if not (isinstance(c.get("dc"), int) and 1 <= c["dc"] <= 30):
                    errors.append(f"{where}: сложность проверки — целое от 1 до 30")
                skill, ability = c.get("skill"), c.get("ability")
                if skill is not None and skill not in SKILLS:
                    errors.append(f"{where}: нет навыка {skill!r}")
                if ability is not None and ability not in ABILITIES:
                    errors.append(f"{where}: нет характеристики {ability!r}")
                if skill is None and ability is None:
                    errors.append(f"{where}: у проверки нужен skill или ability")
            for e in r.get("encounters") or []:
                if not isinstance(e, dict):
                    errors.append(f"{where}: столкновение — объект")
                    continue
                ref = e.get("creature_ref")
                if catalog.raw(str(ref)) is not None and catalog.raw(str(ref)).kind != "creature_template":
                    errors.append(f"{where}: {ref} — не существо")
                if not (isinstance(e.get("count"), int) and 1 <= e["count"] <= 30):
                    errors.append(f"{where}: число существ от 1 до 30")
            for t in r.get("treasure") or []:
                ref = t.get("item_ref") if isinstance(t, dict) else None
                if ref and catalog.raw(str(ref)) is not None and catalog.raw(str(ref)).kind != "item_template":
                    errors.append(f"{where}: {ref} — не предмет")
        for r in rooms:
            bad = [x for x in r.get("exits") or [] if x not in ids]
            if bad:
                errors.append(f"место {lid}, комната {r.get('id')}: выходы в неизвестные комнаты {bad}")


def check(raw: Any, packs_root: Path) -> tuple[dict | None, list[str], list[str]]:
    """Проверяет сдачу переводчика. Возвращает (черновик, [], предупреждения) или (None, ошибки, предупреждения).

    Черновик — сдача с нормализованным каркасом: из него пакет собирается заново при публикации."""
    if not isinstance(raw, dict):
        return None, ["сдача должна быть объектом"], []
    errors: list[str] = []
    slug = raw.get("slug")
    if not isinstance(slug, str) or not SLUG.match(slug):
        return None, [f"slug {slug!r}: латиница, цифры и дефис, от 2 до 40 знаков"], []
    for k in ("title", "summary"):
        if not isinstance(raw.get(k), str) or not raw[k].strip():
            errors.append(f"нет поля {k}")
    levels = raw.get("levels")
    if not (isinstance(levels, dict) and all(isinstance(levels.get(k), int) for k in ("start", "end"))):
        errors.append("levels: {start, end} — целые")
    elif not 1 <= levels["start"] <= levels["end"] <= 20:
        errors.append("levels: от 1 до 20, start не больше end")
    hooks = raw.get("hooks") if isinstance(raw.get("hooks"), list) else []
    if not hooks:
        errors.append("нужна хотя бы одна зацепка (hooks)")
    if not isinstance(raw.get("plot"), dict):
        return None, [*errors, "нет каркаса (plot)"], []

    base = srd(packs_root)
    records, errs = build_records(raw, base)
    errors += errs
    # каркас проверяем по каталогу модуля, поэтому сначала собираем пакет без него
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="tf-module-") as tmp:
        root = write_pack(Path(tmp), slug, "0.0.1", str(raw.get("title") or slug), records)
        try:
            pack, report = load_pack(root, [base])  # SRD уже загружен: второй раз его не читаем
        except PackError as e:
            return None, [*errors, str(e)], []
        chain = [base, pack]
    errors += [e.split(": ", 1)[-1] if e.startswith("data/") else e for e in report.errors]
    if report.overrides:
        errors.append("id совпадают с записями SRD, выберите другие: " + ", ".join(report.overrides))
    if report.unresolved_srd_refs:
        errors.append("srd_ref без записи в SRD: " + ", ".join(report.unresolved_srd_refs))
    if report.customs:
        errors.append(f"op: {CUSTOM_OP} нельзя: возьми ближайший op словаря и опиши отличие в book_note")
    warnings += report.warnings
    catalog = from_packs(chain).view(True)
    _check_rooms(records, catalog.catalog, errors)

    plan, plot_errors = plot.check(raw["plot"], length=plot.MODULE, catalog=catalog, excluded=[])
    errors += [f"каркас: {e}" for e in plot_errors]
    module_locs = {r["id"] for r in records["location_template"]}
    if plan is not None:
        used = {loc.get("template_id") for loc in plan["locations"]}
        missing = sorted(module_locs - used)
        if missing:
            warnings.append("места модуля без места в каркасе: " + ", ".join(missing))
    if errors:
        return None, errors[:MAX_ERRORS], warnings
    draft = copy.deepcopy(raw)
    draft["plot"] = plan
    return draft, [], warnings


def summary(draft: dict) -> dict:
    """Что показать админу: места с комнатами, придуманное и отличия от книги."""
    rooms = sum(len(loc.get("rooms") or []) for loc in draft.get("locations") or [])
    return {
        "locations": [
            {
                "id": loc.get("id"),
                "name": loc.get("name"),
                "rooms": [
                    {"id": r.get("id"), "number": r.get("number"), "name": r.get("name")}
                    for r in loc.get("rooms") or []
                ],
            }
            for loc in draft.get("locations") or []
        ],
        "counts": {
            "locations": len(draft.get("locations") or []),
            "rooms": rooms,
            "creatures": len(draft.get("creatures") or []),
            "items": len(draft.get("items") or []),
            "hooks": len(draft.get("hooks") or []),
            "acts": len((draft.get("plot") or {}).get("acts") or []),
        },
        "creatures": [
            {"id": c.get("id"), "name": c.get("name"), "base_ref": c.get("base_ref"), "book_note": c.get("book_note")}
            for c in draft.get("creatures") or []
        ],
        "items": [
            {"id": i.get("id"), "name": i.get("name"), "category": i.get("category"), "book_note": i.get("book_note")}
            for i in draft.get("items") or []
        ],
        "hooks": [
            {"id": h.get("id"), "title": h.get("title")} for h in draft.get("hooks") or [] if isinstance(h, dict)
        ],
        "notes": [str(n) for n in draft.get("notes") or []],
        "levels": draft.get("levels"),
        "party_size": draft.get("party_size"),
        "summary": draft.get("summary"),
    }


# --- карты ---


def room_numbers(draft: dict) -> dict[str, list[str]]:
    """Номера комнат по местам: что искать на картах."""
    return {
        loc["id"]: [str(r["number"]) for r in loc.get("rooms") or [] if r.get("number")]
        for loc in draft.get("locations") or []
        if isinstance(loc, dict) and loc.get("id")
    }


def map_tool_spec() -> dict:
    cell = {"type": "array", "items": {"type": "integer"}, "description": "Клетка [столбец, строка], счёт с 0."}
    mark = _obj(
        {
            "number": {"type": "string", "description": "Номер комнаты, как он написан на карте."},
            "x": {"type": "number", "description": "Середина номера по горизонтали: доля ширины от 0 (лево) до 1."},
            "y": {"type": "number", "description": "Середина номера по вертикали: доля высоты от 0 (верх) до 1."},
            "cells": _arr(
                {"type": "array", "items": {"type": "integer"}},
                "Пол комнаты прямоугольниками клеток сетки [столбец1, строка1, столбец2, строка2] включительно. "
                "Круглую или неровную комнату покрой несколькими прямоугольниками.",
            ),
            "blocked": _arr(cell, "Клетки комнаты, где стоять нельзя: стены, колонны, гробы, статуи, алтарь."),
        },
        ["number", "x", "y"],
    )
    grid = _obj(
        {
            "cols": {"type": "integer", "description": "Сколько клеток сетки по ширине."},
            "rows": {"type": "integer", "description": "Сколько клеток сетки по высоте."},
            "left": {"type": "number", "description": "Левый край сетки: доля ширины картинки."},
            "top": {"type": "number", "description": "Верхний край сетки: доля высоты."},
            "right": {"type": "number", "description": "Правый край сетки: доля ширины."},
            "bottom": {"type": "number", "description": "Нижний край сетки: доля высоты."},
        },
        ["cols", "rows", "left", "top", "right", "bottom"],
        "Сетка карты. Если сетки нет, не передавай поле.",
    )
    schema = _obj(
        {
            "location_id": {"type": "string", "description": "id места модуля, которое нарисовано на карте."},
            "grid": grid,
            "marks": _arr(mark, "Номера комнат: где стоят, какие клетки занимает комната и какие из них заняты."),
        },
        ["location_id", "marks"],
    )
    return {
        "type": "function",
        "function": {"name": MAP_TOOL, "description": "Сдать место карты, сетку и комнаты.", "parameters": schema},
    }


MAP_SYSTEM = """Ты смотришь на карту из приключения D&D. На ней нарисовано одно место, комнаты подписаны номерами,
поверх обычно лежит сетка клеток по 5 футов.
1. Определи, какое место модуля на карте, по совпадению номеров и планировки с описанием.
2. Найди, где стоит каждый номер: доли размера картинки, x от левого края, y от верхнего, середина цифры.
3. Если есть сетка: сколько в ней столбцов и строк и где её края (доли размера картинки).
4. Для каждой комнаты: какие клетки занимает её пол (прямоугольниками) и какие из них заняты — стены внутри,
   колонны, гробы, статуи, алтарь, всё, на чём нельзя стоять. Там герои не будут показаны.
Сдай ответ вызовом submit_map_marks."""
MAX_GRID = 200


def map_input(draft: dict, taken: dict[str, str] | None = None) -> str:
    lines = []
    for loc in draft.get("locations") or []:
        rooms = ", ".join(f"{r.get('number')} — {r.get('name')}" for r in loc.get("rooms") or [] if r.get("number"))
        lines.append(f"- {loc.get('id')} ({loc.get('name')}): {rooms or 'номеров нет'}")
    text = "Места модуля и номера их комнат:\n" + "\n".join(lines)
    if taken:
        text += "\nЭти места уже нашлись на других картах: " + ", ".join(sorted(taken))
    return text


def _frac(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and 0 <= v <= 1


def _grid(raw: Any, errors: list[str]) -> dict | None:
    if raw in (None, {}):
        return None
    if not isinstance(raw, dict):
        errors.append("grid — объект {cols, rows, left, top, right, bottom}")
        return None
    cols, rows = raw.get("cols"), raw.get("rows")
    if not all(isinstance(v, int) and 1 <= v <= MAX_GRID for v in (cols, rows)):
        errors.append(f"сетка: cols и rows — целые от 1 до {MAX_GRID}")
        return None
    edges = [raw.get(k) for k in ("left", "top", "right", "bottom")]
    if not all(_frac(v) for v in edges) or not (edges[0] < edges[2] and edges[1] < edges[3]):
        errors.append("сетка: края — доли от 0 до 1, left < right и top < bottom")
        return None
    return {"cols": cols, "rows": rows, **{k: round(float(raw[k]), 4) for k in ("left", "top", "right", "bottom")}}


def _cells(m: dict, grid: dict | None, where: str, errors: list[str]) -> tuple[list, list]:
    rects, blocked = m.get("cells") or [], m.get("blocked") or []
    if not rects and not blocked:
        return [], []
    if grid is None:
        errors.append(f"{where}: клетки без сетки — передай grid")
        return [], []
    out_rects = []
    for r in rects:
        ok = isinstance(r, list) and len(r) == 4 and all(isinstance(v, int) for v in r)
        if not ok or not (0 <= r[0] <= r[2] < grid["cols"] and 0 <= r[1] <= r[3] < grid["rows"]):
            errors.append(f"{where}: прямоугольник {r!r} — [столбец1, строка1, столбец2, строка2] внутри сетки")
            continue
        out_rects.append(list(r))
    out_blocked = []
    for c in blocked:
        if not (isinstance(c, list) and len(c) == 2 and all(isinstance(v, int) for v in c)):
            errors.append(f"{where}: занятая клетка {c!r} — [столбец, строка]")
        elif not any(r[0] <= c[0] <= r[2] and r[1] <= c[1] <= r[3] for r in out_rects):
            errors.append(f"{where}: занятая клетка {c} вне комнаты")
        elif list(c) not in out_blocked:
            out_blocked.append(list(c))
    if out_rects and not free_cells({"cells": out_rects, "blocked": out_blocked}):
        errors.append(f"{where}: в комнате не осталось свободных клеток")
    return out_rects, out_blocked


def check_marks(raw: Any, draft: dict) -> tuple[dict | None, list[str]]:
    """Место карты, сетка и комнаты. Номера, которых нет у места, — ошибка; ненайденные — не ошибка."""
    if not isinstance(raw, dict):
        return None, ["ответ должен быть объектом"]
    numbers = room_numbers(draft)
    lid = raw.get("location_id")
    if lid not in numbers:
        return None, [f"нет места {lid!r}; места модуля: {', '.join(numbers)}"]
    errors: list[str] = []
    grid = _grid(raw.get("grid"), errors)
    marks, seen = [], set()
    for m in raw.get("marks") or []:
        if not isinstance(m, dict):
            errors.append("отметка — объект {number, x, y}")
            continue
        n = str(m.get("number", "")).strip()
        x, y = m.get("x"), m.get("y")
        if n not in numbers[lid]:
            errors.append(f"у места {lid} нет комнаты с номером {n!r}")
            continue
        if n in seen:
            errors.append(f"номер {n} отмечен дважды")
            continue
        if not (_frac(x) and _frac(y)):
            errors.append(f"номер {n}: x и y — доли от 0 до 1")
            continue
        seen.add(n)
        mark: dict[str, Any] = {"number": n, "x": round(float(x), 4), "y": round(float(y), 4)}
        rects, blocked = _cells(m, grid, f"комната {n}", errors)
        if rects:
            mark["cells"], mark["blocked"] = rects, blocked
        marks.append(mark)
    if errors:
        return None, errors
    out = {"location_id": lid, "marks": marks, "missing": [n for n in numbers[lid] if n not in seen], "grid": grid}
    return out, []


# --- значки героев на карте ---


def free_cells(mark: dict) -> list[tuple[int, int]]:
    """Клетки комнаты, где можно стоять."""
    blocked = {tuple(c) for c in mark.get("blocked") or []}
    out: list[tuple[int, int]] = []
    for c0, r0, c1, r1 in mark.get("cells") or []:
        for col in range(c0, c1 + 1):
            for row in range(r0, r1 + 1):
                if (col, row) not in blocked and (col, row) not in out:
                    out.append((col, row))
    return out


def cell_center(grid: dict, col: int, row: int) -> tuple[float, float]:
    """Середина клетки в долях картинки: туда клиент ставит значок."""
    w = (grid["right"] - grid["left"]) / grid["cols"]
    h = (grid["bottom"] - grid["top"]) / grid["rows"]
    return round(grid["left"] + (col + 0.5) * w, 4), round(grid["top"] + (row + 0.5) * h, 4)


def place_tokens(grid: dict, mark: dict, tokens: list[tuple[str, float, float]]) -> dict[str, tuple[int, int]]:
    """Клетки для значков в комнате. Токен — (id, сдвиг на восток в футах, сдвиг на север в футах) от середины
    комнаты: так задаются позиции сцены (app/core/positions.py). Значок встаёт на ближайшую к своей точке свободную
    клетку, которую ещё не занял другой значок; стены и колонны (blocked) пропускаются."""
    free = free_cells(mark)
    if not free:
        return {}
    cx = sum(c for c, _ in free) / len(free)
    cy = sum(r for _, r in free) / len(free)
    taken: set[tuple[int, int]] = set()
    out: dict[str, tuple[int, int]] = {}
    for tid, east_ft, north_ft in tokens:
        tx, ty = cx + east_ft / 5, cy - north_ft / 5  # клетка — 5 футов, строки растут к югу
        options = [c for c in free if c not in taken] or free
        best = min(options, key=lambda c: ((c[0] - tx) ** 2 + (c[1] - ty) ** 2, c[1], c[0]))
        taken.add(best)
        out[tid] = best
    return out


# --- публикация ---


def next_version(current: str | None) -> str:
    if not current:
        return "1.0.0"
    major, minor, patch = (int(x) for x in current.split(".")[:3])
    return f"{major}.{minor}.{patch + 1}"


async def publish(
    session: AsyncSession, draft: dict, maps: list[dict], version: str, packs_root: Path, module_id: str
) -> str:
    """Собирает пакет модуля с картами и записывает его в БД. Возвращает id пакета."""
    base = srd(packs_root)
    records, errors = build_records(draft, base)
    if errors:
        raise ModuleError("; ".join(errors[:5]))
    records["adventure"] = [adventure_record(draft, draft["plot"], maps, module_id)]
    with tempfile.TemporaryDirectory(prefix="tf-module-") as tmp:
        root = write_pack(Path(tmp), draft["slug"], version, draft["title"], records)
        try:
            await import_pack(session, root, packs_root)
        except PackError as e:
            raise ModuleError(str(e)) from e
    return f"module-{draft['slug']}"
