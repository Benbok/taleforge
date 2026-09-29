"""Панель живого мастера (этап 7, часть 6): те же инструменты, что у ИИ-мастера, в виде форм.

Сервер отдаёт схемы аргументов со списками допустимых значений на этот момент и подписи к id, чтобы мастер
выбирал из списка, а не вводил id руками. Проверяет вызов всё равно ``execute``: список — удобство, не защита.
Отдаётся только месту мастера: в нём каркас сюжета и скрытые сущности сцены.
"""

from __future__ import annotations

from typing import Any

from app.core.plot import _index, has_plan
from app.core.rolls import ABILITY_RU, SKILL_RU
from app.core.standing import book as standing_book
from app.core.standing import ripen
from app.core.world import World
from app.tools import fortune as _fortune_tools  # noqa: F401
from app.tools import master as _master_tools  # noqa: F401  (регистрирует инструменты)
from app.tools import plot as _plot_tools  # noqa: F401
from app.tools import progress as _progress_tools  # noqa: F401
from app.tools import standing as _standing_tools  # noqa: F401
from app.tools.registry import REGISTRY, _enum_values

# вкладки панели; инструмент без группы попадает в «Инструменты»
GROUPS: dict[str, list[str]] = {
    "scene": [
        "get_scene",
        "set_scene_mode",
        "advance_time",
        "spawn_entity",
        "update_entity",
        "create_location",
        "move",
        "apply_hazard",
        "place_item",
        "roll_fortune",
    ],
    "checks": ["roll_check", "resolve_attack", "death_save", "auto_success", "cancel_action"],
    "players": [
        "get_character",
        "whisper",
        "give_item",
        "take_item",
        "pick_up_item",
        "keep_found_item",
        "drop_item",
        "pass_item",
        "equip_item",
        "use_item",
        "apply_effect",
        "remove_effect",
        "rest",
        "award_xp",
        "grant_inspiration",
        "grant_level",
        "cross_threshold",
        "reveal_knowledge",
        "learn_fact",
        "review_character",
    ],
    "plot": ["get_plot", "advance_plot", "plot_reveal", "end_act", "develop", "threat_tick"],
    "standing": ["get_standing", "record_deed", "expose_deed", "resolve_response"],
    "templates": ["lookup_template"],
}

# поля, которые реестр не перечисляет (слишком длинные списки для модели), а форме список нужен
EXTRA_FIELDS: dict[tuple[str, str], str] = {
    ("apply_effect", "effect_template_id"): "templates:effect_template",
    ("cross_threshold", "lineage_id"): "templates:lineage",
    ("give_item", "item_template_id"): "templates:item_template",
    ("place_item", "item_template_id"): "templates:item_template",
    ("create_location", "template_id"): "templates:location_template",
    ("remove_effect", "effect_id"): "effects",
    ("roll_check", "stat"): "stats",
    ("update_entity", "zone"): "zones",
    ("update_entity", "attitude"): "attitudes",
    ("reveal_knowledge", "level"): "levels",
    ("record_deed", "subject_id"): "standing_subjects",
    ("expose_deed", "deed_id"): "secret_deeds",
    ("resolve_response", "response_id"): "responses",
    ("roll_fortune", "table_id"): "fortune_tables",
}

ZONES = {"melee": "вплотную", "near": "близко", "far": "далеко"}
ATTITUDES = {"hostile": "враждебно", "neutral": "нейтрально", "friendly": "дружелюбно"}
LEVELS = {"1": "1: внешность", "2": "2: повадки", "3": "3: слабости", "4": "4: всё"}


def _values(world: World, key: str) -> list[str]:
    if key == "effects":
        return [e.id for e in world.effects]
    if key == "stats":
        return list(ABILITY_RU) + list(SKILL_RU)
    if key == "zones":
        return list(ZONES)
    if key == "attitudes":
        return list(ATTITUDES)
    if key == "levels":
        return list(LEVELS)
    if key == "standing_subjects":  # фракции мира, NPC и места реестра
        ents = [e.id for e in world.entities.values() if e.kind in ("creature", "location")]
        return [r.id for r in world.catalog.by_kind("faction")] + ents
    if key in ("secret_deeds", "responses"):
        b = standing_book(world.scene.state)
        ripen(b, int(world.scene.game_time))
        if key == "secret_deeds":
            return [d["id"] for d in b["hidden"]]
        return [r["id"] for r in b["responses"] if r["status"] == "ready"]
    if key == "fortune_tables":
        return [r.id for k in ("encounter_table", "event_table", "loot_table") for r in world.catalog.by_kind(k)]
    return _enum_values(world, key)


def _name(world: World, rid: str) -> str:
    rec = world.catalog.find(rid)
    return rec.name if rec else rid


def _labels(world: World) -> dict[str, str]:
    """Подписи ко всем id, которые могут попасть в списки: имена героев, сущностей, предметов, записей каталога."""
    out: dict[str, str] = {**ABILITY_RU, **SKILL_RU, **ZONES, **ATTITUDES, **LEVELS}
    for ch in world.characters.values():
        out[ch.id] = ch.name
    for e in world.entities.values():
        out[e.id] = e.name
    for owner, items in world.inventory.items():
        who = world.characters[owner].name if owner in world.characters else owner
        for it in items:
            name = it.display_name or _name(world, it.item_template_id)
            out[it.id] = f"{name}{f' ×{it.qty}' if it.qty > 1 else ''} ({who})"
    for e in world.effects:
        target = out.get(e.target_id, e.target_id)
        out[e.id] = f"{_name(world, e.effect_template_id)} ({target})"
    b = standing_book(world.scene.state)
    for d in b["hidden"]:
        out[d["id"]] = f"{d['name']}: {d['text']}"[:120]
    for r in b["responses"]:
        out[r["id"]] = f"{r['name']}: {'благодарность' if r['mood'] == 'gratitude' else 'месть'}"
    for kind in (
        "effect_template",
        "item_template",
        "location_template",
        "creature_template",
        "hazard_template",
        "faction",
        "encounter_table",
        "event_table",
        "loot_table",
    ):
        for rec in world.catalog.by_kind(kind):
            out[rec.id] = rec.name
    for rec in world.catalog.dc_scale():
        out[rec.id] = f"{rec.name} ({rec.data.get('value')})"
    if has_plan(world.plot):
        for pid, (_kind, x) in _index(world.plot).items():
            out[pid] = str(x.get("name") or x.get("title") or x.get("summary") or pid)[:120]
    return out


def panel(world: World) -> dict[str, Any]:
    tools = []
    grouped = {name: group for group, names in GROUPS.items() for name in names}
    for t in REGISTRY.values():
        schema = t.args.model_json_schema()
        props = schema.get("properties", {})
        fields = []
        for fname, p in props.items():
            key = t.id_fields.get(fname) or EXTRA_FIELDS.get((t.name, fname))
            types = [p.get("type")] + [x.get("type") for x in p.get("anyOf", [])]
            items = p.get("items") or next((x.get("items") for x in p.get("anyOf", []) if x.get("items")), None)
            enum = p.get("enum") or next((x.get("enum") for x in p.get("anyOf", []) if x.get("enum")), None)
            fields.append(
                {
                    "name": fname,
                    "type": next((x for x in types if x and x != "null"), "string"),
                    "many": "array" in types or bool(items),
                    "required": fname in schema.get("required", []),
                    "nullable": "null" in types,
                    "default": p.get("default"),
                    "description": p.get("description", ""),
                    "options": _values(world, key) if key else enum,
                    "min": p.get("minimum"),
                    "max": p.get("maximum"),
                    "max_length": p.get("maxLength"),
                }
            )
        tools.append(
            {
                "name": t.name,
                "description": t.description,
                "group": grouped.get(t.name, "other"),
                "mutating": t.mutating,
                "fields": fields,
            }
        )
    return {"tools": tools, "labels": _labels(world), "has_plot": has_plan(world.plot)}
