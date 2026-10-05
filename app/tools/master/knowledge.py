"""Знания героев: раскрытие знаний и факты о сущностях."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.db.models import Knowledge, KnownFact
from app.tools.master.base import _character
from app.tools.registry import ToolContext, ToolError, tool


class RevealArgs(BaseModel):
    character_id: str
    entity_id: str
    level: int = Field(ge=0, le=3, description="0 — видел, 1 — наслышан, 2 — изучил, 3 — знает всё")


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
    row = await ctx.session.get(Knowledge, (ch.id, a.entity_id))
    before = row.level if row else None
    if row is None:
        row = Knowledge(character_id=ch.id, entity_id=a.entity_id, level=a.level)
        ctx.session.add(row)
    else:
        row.level = max(row.level, a.level)
    await ctx.session.flush()
    await ctx.record(
        "reveal_knowledge",
        actor_id=ch.id,
        target_id=a.entity_id,
        payload={"level": row.level},
        inverse=[{"table": "knowledge", "id": [ch.id, a.entity_id], "field": "level", "before": before}],
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
