"""Знания героев: раскрытие знаний и факты о сущностях."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core import map_memory
from app.core.layout import store
from app.core.object_policy import observe
from app.db.models import Knowledge, KnownFact, now
from app.tools.master.base import _character
from app.tools.registry import ToolContext, ToolError, tool


class RevealArgs(BaseModel):
    character_id: str
    entity_id: str
    level: int = Field(ge=0, le=3, description="0 — видел, 1 — наслышан, 2 — изучил, 3 — знает всё")
    discovered: bool = Field(
        False,
        description="true — герой нашёл сам тайный предмет или существо (тайник, скрытый шкаф): теперь видит его "
        "на схеме. Слух и рассказ — false: знание без обнаружения",
    )


class RevealAreaArgs(BaseModel):
    character_ids: list[str] = Field(min_length=1, max_length=8, description="герои, которым открывается участок")
    location_id: str = Field(description="участок комплекса")
    passage_refs: list[str] = Field(default_factory=list, max_length=8, description="тайные проходы")
    reason: str = Field(min_length=3, max_length=300, description="почему мастер открыл карту")


@tool(
    "reveal_area",
    "Открывает выбранным героям готовую геометрию участка и указанные тайные проходы.",
    RevealAreaArgs,
    ids={"location_id": "locations", "character_ids": "characters"},
    closes=False,
)
async def reveal_area(ctx: ToolContext, a: RevealAreaArgs) -> dict:
    heroes = []
    for cid in dict.fromkeys(a.character_ids):
        heroes.append(_character(ctx, cid))
    area = ctx.world.entities.get(a.location_id)
    if area is None or area.kind != "location":
        raise ToolError("нет такого участка")
    complex_state = (area.state or {}).get("complex") or {}
    root = ctx.world.entities.get(complex_state.get("root_id"))
    if root is None or not store.blueprint_of(root):
        raise ToolError("участок ещё не подготовлен")
    if not (area.state or {}).get("sketch", {}).get("cols"):
        raise ToolError("геометрия участка ещё не готова")
    inverse: list[dict] = []
    await map_memory.observe_area(ctx, area.id, [hero.id for hero in heroes], inverse, explicit=True)
    bp = store.blueprint_of(root)
    refs = []
    if bp is not None:
        for ref in dict.fromkeys(a.passage_refs):
            if bp.passage(ref) is None:
                raise ToolError("отсюда нет такого прохода")
            refs.append(ref)
    for ref in refs:
        await map_memory.discover_passage(ctx, root.id, ref, [hero.id for hero in heroes], inverse)
    ctx.signals.add("map.changed")
    await ctx.record(
        "reveal_area",
        target_id=area.id,
        payload={
            "characters": [hero.id for hero in heroes],
            "location_id": area.id,
            "passage_refs": refs,
            "reason": a.reason,
        },
        inverse=inverse,
        hidden=True,
    )
    return {"location_id": area.id, "revealed": [hero.id for hero in heroes], "passage_refs": refs}


@tool(
    "reveal_knowledge",
    "Открывает персонажу сведения о сущности до уровня знаний.",
    RevealArgs,
    ids={"character_id": "characters", "entity_id": "entities"},
    closes=False,
)
async def reveal_knowledge(ctx: ToolContext, a: RevealArgs) -> dict:
    ch = _character(ctx, a.character_id)
    if a.entity_id not in ctx.world.entities:
        raise ToolError(f"нет сущности {a.entity_id}")
    entity = ctx.world.entities[a.entity_id]
    if a.discovered and (entity.kind not in ("object", "creature") or entity.location_id != ctx.world.place_of(ch)):
        raise ToolError(f"{ch.name} может обнаружить только предмет или существо там, где стоит сам")
    row = await ctx.session.get(Knowledge, (ch.id, a.entity_id))
    before = row.level if row else None
    if row is None:
        row = Knowledge(character_id=ch.id, entity_id=a.entity_id, level=a.level)
        ctx.session.add(row)
    else:
        row.level = max(row.level, a.level)
    inverse: list = [{"table": "knowledge", "id": [ch.id, a.entity_id], "field": "level", "before": before}]
    if a.discovered and row.revealed_at is None:
        inverse.append({"table": "knowledge", "id": [ch.id, a.entity_id], "field": "revealed_at", "before": None})
        row.revealed_at = now()
        ctx.world.revealed.setdefault(ch.id, set()).add(entity.id)
    await ctx.session.flush()
    if a.discovered:
        await observe(ctx, entity.location_id, inverse, only=[entity.id])
        ctx.signals.add("map.changed")
    await ctx.record(
        "reveal_knowledge",
        actor_id=ch.id,
        target_id=a.entity_id,
        payload={"level": row.level, **({"discovered": True} if a.discovered else {})},
        inverse=inverse,
    )
    return {"character": ch.name, "entity": ctx.world.entities[a.entity_id].name, "level": row.level}


class FactArgs(BaseModel):
    character_ids: list[str] = Field(
        min_length=1, max_length=8, description="кто из героев это узнал (обычно все, кто был в сцене)"
    )
    subject_id: str = Field(description="о ком или о чём факт: id сущности, места или героя")
    fact: str = Field(
        min_length=3,
        max_length=300,
        description="что герои теперь знают, одной фразой от третьего лица: «Староста боится леса». "
        "Только то, что они действительно узнали, без тайн, до которых не добрались",
    )


@tool(
    "learn_fact",
    "Герои узнали факт о NPC, месте, существе или другом герое: он появится в карточке по клику на имя "
    "у тех, кто узнал. Вызывай, когда в сцене прозвучало что-то новое и важное.",
    FactArgs,
    ids={"subject_id": "subjects"},
    closes=False,
)
async def learn_fact(ctx: ToolContext, a: FactArgs) -> dict:
    w = ctx.world
    subject = w.entities.get(a.subject_id) or w.characters.get(a.subject_id)
    if subject is None:
        raise ToolError(f"нет сущности или героя {a.subject_id}")
    text = " ".join(a.fact.split())
    names = []
    for cid in dict.fromkeys(a.character_ids):
        ch = _character(ctx, cid)
        row = KnownFact(campaign_id=ctx.campaign.id, character_id=ch.id, subject_id=a.subject_id, text=text)
        ctx.session.add(row)
        if a.subject_id in w.entities and await ctx.session.get(Knowledge, (ch.id, a.subject_id)) is None:
            ctx.session.add(Knowledge(character_id=ch.id, entity_id=a.subject_id, level=0))  # теперь он о нём знает
        await ctx.session.flush()
        await ctx.record(
            "learn_fact",
            actor_id=ch.id,
            target_id=a.subject_id,
            payload={"fact": text},
            inverse=[{"table": "known_facts", "op": "delete", "id": row.id}],
        )
        names.append(ch.name)
    return {"learned": names, "subject": subject.name, "fact": text}
