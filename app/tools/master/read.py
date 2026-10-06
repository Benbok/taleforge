"""Чтение: сцена, лист героя, порог между местами, шаблоны пакета."""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from app.core.features import class_rows, uses_view, wild_shape_forms
from app.core.world import lineage_features
from app.db.models import Character
from app.tools.master.base import _character
from app.tools.registry import ToolContext, ToolError, tool

# --- чтение ---


class NoArgs(BaseModel):
    pass


@tool("get_scene", "Сцена: сущности с id, хиты, зоны, эффекты, режим и игровое время.", NoArgs, mutating=False)
async def get_scene(ctx: ToolContext, a: NoArgs) -> dict:
    return {"scene": ctx.world.scene_table()}


class CharacterArg(BaseModel):
    character_id: str


@tool(
    "get_character",
    "Актуальный лист персонажа: характеристики, навыки, атаки, хиты, эффекты, снаряжение.",
    CharacterArg,
    mutating=False,
    ids={"character_id": "characters"},
    closes=False,
)
async def get_character(ctx: ToolContext, a: CharacterArg) -> dict:
    ch = _character(ctx, a.character_id)
    act = ctx.world.actor(ch.id)
    return {
        "id": ch.id,
        "name": ch.name,
        "class": (ch.sheet or {}).get("class_id"),
        "origin": (ch.sheet or {}).get("origin_id"),
        "lineage": (ch.sheet or {}).get("lineage_id"),
        "lineage_caste": (ch.sheet or {}).get("lineage_caste"),
        "level": (ch.sheet or {}).get("level", 1),
        "status": act.status(),
        "ac": act.ac,
        "abilities": act.abilities,
        "saves": act.saves,
        "skills": act.skills,
        "attacks": act.attacks,
        "effects": [{"id": e.id, "template": r.id, "name": r.name, "stacks": e.stacks} for e, r in act.effects],
        "inventory": [
            {
                "id": it.id,
                "item": it.item_template_id,
                "name": ctx.world.item_name(it),
                "qty": it.qty,
                "equipped": it.equipped,
            }
            for it in ctx.world.inventory.get(ch.id, [])
        ],
        "personality": ch.personality,
        "public_bio": ch.public_bio,
        "features": uses_view(ch, ctx.world.catalog, act.mods, act.pb),
        # все умения класса на уровне героя с текстом SRD: сервер сам считает КД, скорость, компетентность, ярость,
        # скрытую атаку и подобное; остальное мастер исполняет по тексту
        "class_features": class_rows(ch, ctx.world.catalog),
        **_wild_shape(ctx, ch),
        **_spellbook(ctx, ch),
    }


def _wild_shape(ctx: ToolContext, ch: Character) -> dict:
    forms = wild_shape_forms(ch, ctx.world.catalog)
    if forms is None:
        return {}
    return {"wild_shape_forms": forms}


def _spellbook(ctx: ToolContext, ch: Character) -> dict:
    """Заклинания героя для мастера: сложность, бонус атаки, ячейки и что он может сотворить (для cast_spell)."""
    from app.core.spells import book_view

    b = book_view(ch.sheet or {}, ch.resources or {}, ctx.world.catalog)
    if b is None:
        return {}
    return {
        "spellcasting": {
            "save_dc": b["save_dc"],
            "attack": b["attack"],
            "slots_left": b["slots_left"],
            "pact_left": b["pact_left"] if b["pact_slots"] else None,
            "concentration": (b["concentration"] or {}).get("name"),
            "spells": [
                {"id": x["id"], "name": x["name"], "level": x["level"], "ritual": x["ritual"]}
                for x in b["spells"]
                if x["prepared"]
            ],
        }
    }


class ThresholdArgs(BaseModel):
    character_id: str
    lineage_id: str = Field(description="вторая раса из данных пакета (kind lineage), например lineage.kept_self")
    caste: str = Field(description="id касты из поля castes этой расы: игрок выбирает её сам")
    variant: str | None = Field(None, description="исход испытания из поля variants, если оно есть у расы")


@tool(
    "cross_threshold",
    "Герой прошёл испытание Порога, сохранив личность: получает вторую расу пакета поверх человеческого "
    "происхождения и выбранную игроком касту. Класс, уровень, характеристики и черты происхождения остаются. "
    "Вызывай только по итогу испытания из правил пакета, не по просьбе игрока.",
    ThresholdArgs,
    ids={"character_id": "characters"},
)
async def cross_threshold(ctx: ToolContext, a: ThresholdArgs) -> dict:
    ch = _character(ctx, a.character_id)
    lin = ctx.world.catalog.find(a.lineage_id, "lineage")
    if lin is None:
        raise ToolError(f"в мире кампании нет второй расы {a.lineage_id}")
    sheet = ch.sheet or {}
    if sheet.get("lineage_id"):
        raise ToolError(f"{ch.name} уже прошёл Порог")
    castes = {c.get("id"): c for c in lin.data.get("castes") or []}
    if castes and a.caste not in castes:
        raise ToolError(f"у расы {lin.name} нет касты {a.caste}: есть {', '.join(castes)}")
    variants = {v.get("id") for v in lin.data.get("variants") or []}
    if a.variant and a.variant not in variants:
        raise ToolError(f"у расы {lin.name} нет исхода {a.variant}")
    inverse = [
        {"table": "characters", "id": ch.id, "field": "sheet", "before": copy.deepcopy(sheet)},
        {"table": "characters", "id": ch.id, "field": "resources", "before": copy.deepcopy(ch.resources)},
    ]
    new = {**sheet, "lineage_id": lin.id, "lineage_caste": a.caste if castes else None}
    if a.variant:
        new["lineage_variant"] = a.variant
    ch.sheet = new
    # шкалы, которые форма обнуляет (op set со значением-числом у ресурса пакета): Скверна, Перемена, зависимость
    res = copy.deepcopy(ch.resources or {})
    stats = dict(res.get("stats") or {})
    _, caste, feats = lineage_features(new, ctx.world.catalog)
    for f in feats:
        for m in f.get("modifiers") or []:
            tgt = m.get("target")
            if m.get("op") == "set" and isinstance(m.get("value"), int) and ctx.world.catalog.find(f"stat.{tgt}"):
                stats[tgt] = m["value"]
    res["stats"] = stats
    ch.resources = res
    result = {
        "character": ch.name,
        "lineage": lin.name,
        "caste": (caste or {}).get("name"),
        "features": [f.get("name") for f in feats],
    }
    await ctx.record("cross_threshold", target_id=ch.id, payload=result, inverse=inverse)
    return result


TemplateKind = Literal[
    "creature_template",
    "item_template",
    "effect_template",
    "hazard_template",
    "location_template",
    "dc_scale",
    "faction",
    "lore_fact",
    "class",
    "origin",
    "lineage",
]


class LookupArgs(BaseModel):
    kind: TemplateKind
    query: str = Field("", description="слова для поиска: название, тег, английское имя SRD")


@tool(
    "lookup_template",
    "Поиск шаблонов в данных кампании. Предмет, существо, эффект или опасность можно создать только из шаблона.",
    LookupArgs,
    mutating=False,
)
async def lookup_template(ctx: ToolContext, a: LookupArgs) -> dict:
    found = ctx.world.catalog.search(a.kind, a.query, limit=8)
    out = []
    for e in found:
        d = e.data
        item = {"id": e.id, "name": e.name}
        for k in ("description", "cr", "category", "value", "ac", "tags", "duration"):
            if d.get(k) not in (None, "", []):
                item[k] = d[k] if k != "description" else str(d[k])[:240]
        if d.get("castes"):  # вторая раса: мастеру нужны касты и исходы, чтобы провести Порог
            item["castes"] = [{"id": c.get("id"), "name": c.get("name")} for c in d["castes"]]
            item["variants"] = [v.get("id") for v in d.get("variants") or []]
        out.append(item)
    return {"results": out, "note": "" if out else "ничего не найдено: такого в мире нет"}
