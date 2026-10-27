"""Чтение: сцена, лист героя, порог между местами, шаблоны пакета."""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from app.core.world import lineage_features
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
    from app.core.universal.exploration_views import exploration_game_card

    return await exploration_game_card(ctx.session, _character(ctx, a.character_id))


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
