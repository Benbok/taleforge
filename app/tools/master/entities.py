"""Реестр мира: сущности и бюджет встречи по SRD."""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from app.core import positions as grid
from app.core.positions import areas_at
from app.core.world import PLAYABLE
from app.db.models import Entity
from app.tools.master.base import (
    BEARING_HINT,
    CELL_HINT,
    COVER_HINT,
    ELEVATION_HINT,
    PLACE_HINT,
    Bearing,
    Cell,
    Cover,
    Elevation,
    Zone,
)
from app.tools.master.checks import enter_areas
from app.tools.registry import ToolContext, ToolError, tool

# --- реестр мира ---

ENCOUNTER_XP = {  # SRD 5.1: пороги опыта на персонажа (лёгкая, средняя, трудная, смертельная)
    1: (25, 50, 75, 100),
    2: (50, 100, 150, 200),
    3: (75, 150, 225, 400),
    4: (125, 250, 375, 500),
    5: (250, 500, 750, 1100),
    6: (300, 600, 900, 1400),
    7: (350, 750, 1100, 1700),
    8: (450, 900, 1400, 2100),
    9: (550, 1100, 1600, 2400),
    10: (600, 1200, 1900, 2800),
    11: (800, 1600, 2400, 3600),
    12: (1000, 2000, 3000, 4500),
    13: (1100, 2200, 3400, 5100),
    14: (1250, 2500, 3800, 5700),
    15: (1400, 2800, 4300, 6400),
    16: (1600, 3200, 4800, 7200),
    17: (2000, 3900, 5900, 8800),
    18: (2100, 4200, 6300, 9500),
    19: (2400, 4900, 7300, 10900),
    20: (2800, 5700, 8500, 12700),
}
MULTIPLIERS = (1, 1.5, 2, 2.5, 3, 4)
# Сложность кампании → потолок встречи: какой порог SRD нельзя превышать (индекс в ENCOUNTER_XP) и множитель
DIFFICULTY_CAP = {"easy": (1, 1.0), "normal": (2, 1.0), "hard": (3, 1.0), "deadly": (3, 1.5)}


def _multiplier(count: int, party: int) -> float:
    idx = 0 if count <= 1 else 1 if count == 2 else 2 if count <= 6 else 3 if count <= 10 else 4 if count <= 14 else 5
    if party < 3:
        idx = min(idx + 1, len(MULTIPLIERS) - 1)
    elif party >= 6:
        idx = max(idx - 1, 0)
    return MULTIPLIERS[idx]


def encounter_budget(ctx: ToolContext, adding: list[dict], place: str | None = None) -> dict:
    """Бюджет встречи SRD: опыт враждебных существ с множителем против порога отряда (раздел 8.1). Разделившийся
    отряд считается по месту: встречу в трюме держат только те, кто в трюме."""
    w = ctx.world
    party = [c for c in w.characters.values() if c.status in PLAYABLE and (place is None or w.place_of(c) == place)]
    if not party:
        return {"ok": True, "note": "в игре нет героев"}
    cap_idx, factor = DIFFICULTY_CAP.get(ctx.campaign.difficulty, (2, 1.0))
    cap = sum(ENCOUNTER_XP[max(1, min(20, int((c.sheet or {}).get("level", 1))))][cap_idx] for c in party) * factor
    xp = [x for x in adding]
    for en in ctx.world.in_scene_entities(place):
        st = en.state or {}
        if en.kind == "creature" and not st.get("dead") and st.get("attitude", "hostile") == "hostile":
            rec = ctx.world.catalog.find(en.template_id or "")
            xp.append({"xp": int((rec.data.get("xp") if rec else 0) or 0)})
    total = sum(x["xp"] for x in xp)
    adjusted = total * _multiplier(len(xp), len(party))
    return {"ok": adjusted <= cap, "adjusted_xp": int(adjusted), "cap": int(cap), "party": len(party)}


class SpawnArgs(BaseModel):
    creature_template_id: str
    name: str = Field(max_length=128, description="имя экземпляра, например «Гоблин-лучник»")
    count: int = Field(1, ge=1, le=12)
    zone: Zone = "near"
    bearing: Bearing | None = Field(None, description=BEARING_HINT)
    cell: Cell | None = Field(None, description=CELL_HINT + "; несколько существ встают на свободные клетки вокруг")
    attitude: Literal["hostile", "neutral", "friendly"] = "hostile"
    description: str = Field(
        "",
        max_length=1000,
        description="внешность и манера, как их видят герои: это текст карточки для игроков. Мотивы и тайны сюда "
        "не пиши",
    )
    location_id: str | None = Field(None, description=PLACE_HINT)


@tool(
    "spawn_entity",
    "Выставляет существо или NPC из шаблона в текущую локацию. Враждебные проверяются бюджетом встречи.",
    SpawnArgs,
    ids={"creature_template_id": "templates:creature_template", "location_id": "places"},
)
async def spawn_entity(ctx: ToolContext, a: SpawnArgs) -> dict:
    from app.core.world import creature_stats

    rec = ctx.world.catalog.get(a.creature_template_id, "creature_template")
    creature_stats(rec.data)  # без блока статов существо в сцену не выходит
    place = ctx.world.place_arg(a.location_id, "появляется существо")
    if a.attitude == "hostile":
        b = encounter_budget(ctx, [{"xp": int(rec.data.get("xp") or 0)} for _ in range(a.count)], place)
        if not b["ok"]:
            raise ToolError(
                f"встреча превышает бюджет сложности кампании ({ctx.campaign.difficulty}: "
                f"{b['adjusted_xp']} > {b['cap']} опыта с поправкой на "
                f"число существ, героев: {b['party']}). Выставьте меньше или слабее"
            )
    hp = int((rec.data.get("hp") or {}).get("average", 1))
    cells: list = [None] * a.count
    if a.cell is not None:
        start = grid.to_rel(ctx.world, place, a.cell)
        problem = grid.cell_problem(ctx.world, place, start)
        if problem:
            raise ToolError(problem)
        cells = grid.free_cells_near(ctx.world, place, start, a.count)
        if len(cells) < a.count:
            raise ToolError(f"рядом с клеткой {a.cell} нет места для {a.count} существ")
    created = []
    for i in range(a.count):
        name = a.name if a.count == 1 else f"{a.name} {i + 1}"
        en = Entity(
            campaign_id=ctx.campaign.id,
            kind="creature",
            name=name,
            template_id=rec.id,
            description=a.description,
            state={"hp": hp, "hp_max": hp, "attitude": a.attitude, **({"bearing": a.bearing} if a.bearing else {})},
            location_id=place,
            zone=a.zone,
        )
        ctx.session.add(en)
        await ctx.session.flush()
        ctx.world.entities[en.id] = en
        if cells[i] is not None:
            grid.set_cell(ctx.world, en.id, cells[i])
        created.append({"id": en.id, "name": name})
        await ctx.record(
            "spawn_entity",
            target_id=en.id,
            payload={"template": rec.id, "name": name, "attitude": a.attitude, "zone": a.zone},
            inverse=[{"table": "entities", "op": "delete", "id": en.id}],
        )
    return {"spawned": created, "template": rec.name, "hp": hp, "ac": rec.data.get("ac")}


class UpdateEntityArgs(BaseModel):
    entity_id: str
    attitude: Literal["hostile", "neutral", "friendly"] | None = None
    mood: str | None = Field(None, max_length=64)
    note: str | None = Field(None, max_length=500, description="нарративная пометка: мотив, что пообещал")
    zone: Zone | None = Field(
        None, description="сблизился или отошёл: вплотную, близко, далеко; снимает с клетки, точнее — reposition с cell"
    )
    bearing: Bearing | None = Field(None, description=BEARING_HINT)
    elevation: Elevation | None = Field(None, description=ELEVATION_HINT)
    cover: Cover | None = Field(None, description=COVER_HINT)
    fled: bool | None = Field(None, description="существо ушло со сцены")


@tool(
    "update_entity",
    "Меняет нарративные поля сущности: отношение, настроение, зону и сторону на схеме, пометки. Хиты и статы так "
    "не меняются.",
    UpdateEntityArgs,
    ids={"entity_id": "entities"},
    closes=False,
)
async def update_entity(ctx: ToolContext, a: UpdateEntityArgs) -> dict:
    en = ctx.world.entities.get(a.entity_id)
    if en is None:
        raise ToolError(f"нет сущности {a.entity_id}")
    inverse = [
        {"table": "entities", "id": en.id, "field": "state", "before": copy.deepcopy(en.state)},
        {"table": "entities", "id": en.id, "field": "zone", "before": en.zone},
        {"table": "entities", "id": en.id, "field": "location_id", "before": en.location_id},
    ]
    was = {x.id for x in areas_at(ctx.world, en.id)} if en.kind == "creature" else set()
    st = dict(en.state or {})
    changes = {}
    for k in ("attitude", "mood", "note", "bearing", "elevation", "cover"):
        v = getattr(a, k)
        if v is not None:
            st[k] = v
            changes[k] = v
    if a.zone is not None:
        en.zone = a.zone
        changes["zone"] = a.zone
    if a.zone is not None or a.bearing is not None:
        st.pop("cell", None)  # зона и сторона заменяют точную клетку
    if a.fled:
        en.location_id = None
        changes["fled"] = True
    en.state = st
    ctx.world.invalidate(en.id)
    await ctx.record("update_entity", target_id=en.id, payload={"name": en.name, **changes}, inverse=inverse)
    out = {"entity": en.name, **changes}
    if en.kind == "creature" and en.location_id is not None:
        hit = await enter_areas(ctx, en.id, was)
        if hit:
            out["areas"] = hit
    return out
