"""Общение и контракт намерения: шёпот, отказ, автоуспех, моменты, проверка героя."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.campaigns import master_seat
from app.db.models import ActiveEffect
from app.tools.master.base import _character
from app.tools.registry import ToolContext, ToolError, tool

# --- общение и контракт намерения ---


class WhisperArgs(BaseModel):
    character_id: str = Field(description="персонаж, чьему игроку уйдёт личное сообщение")
    text: str = Field(min_length=1, max_length=2000)


@tool(
    "whisper",
    "Личное сообщение одному игроку: видят только он и мастер.",
    WhisperArgs,
    ids={"character_id": "characters"},
    closes=False,
)
async def whisper(ctx: ToolContext, a: WhisperArgs) -> dict:
    ch = _character(ctx, a.character_id)
    if ch.seat_id is None:
        raise ToolError(f"у персонажа {ch.name} нет игрока")
    ms = master_seat(ctx.campaign)
    # Номер сообщения выдаётся при фиксации хода: строку кампании нельзя держать заблокированной весь ход
    ctx.outbox.append({"kind": "narration", "seat_id": ms.id, "visible_to": [ch.seat_id, ms.id], "content": a.text})
    await ctx.record("whisper", target_id=ch.id, payload={"text": a.text}, hidden=True)
    return {"sent_to": ch.name}


class ReasonArgs(BaseModel):
    character_id: str
    reason: str = Field(min_length=1, max_length=500)


@tool(
    "cancel_action",
    "Явный отказ в действии игрока с причиной: цель скрылась, дверь уже открыта.",
    ReasonArgs,
    ids={"character_id": "characters"},
)
async def cancel_action(ctx: ToolContext, a: ReasonArgs) -> dict:
    ch = _character(ctx, a.character_id)
    await ctx.record("cancel_action", target_id=ch.id, payload={"reason": a.reason})
    return {"character": ch.name, "cancelled": a.reason}


@tool(
    "auto_success",
    "Тривиальное действие без броска: открыть незапертую дверь, поднять монету.",
    ReasonArgs,
    ids={"character_id": "characters"},
)
async def auto_success(ctx: ToolContext, a: ReasonArgs) -> dict:
    ch = _character(ctx, a.character_id)
    await ctx.record("auto_success", target_id=ch.id, payload={"reason": a.reason})
    return {"character": ch.name, "success": a.reason}


MOMENTS = {
    "betrayal": "предательство",
    "rescue": "спасение",
    "failure": "крупный провал",
    "victory": "крупная победа",
    "loss": "тяжёлая потеря",
}


class MomentArgs(BaseModel):
    kind: Literal["betrayal", "rescue", "failure", "victory", "loss"] = Field(
        description="betrayal — предательство, rescue — спасение, failure — крупный провал, "
        "victory — крупная победа, loss — тяжёлая потеря (не гибель героя: её сервер видит сам)"
    )
    character_ids: list[str] = Field(default_factory=list, description="герои, которых это задело")
    text: str = Field(min_length=1, max_length=300, description="что случилось, одной фразой")


@tool(
    "mark_moment",
    "Отмечает сильный момент для летописи характера героев под ИИ и ИИ-мастера: предательство, спасение, "
    "крупный провал или победу, тяжёлую потерю. Только по-настоящему поворотное, не каждый удачный бросок. "
    "Игроки отметку не видят.",
    MomentArgs,
    ids={"character_ids": "characters"},
    closes=False,
)
async def mark_moment(ctx: ToolContext, a: MomentArgs) -> dict:
    names = [_character(ctx, cid).name for cid in a.character_ids]
    await ctx.record(
        "mark_moment",
        payload={"kind": a.kind, "label": MOMENTS[a.kind], "characters": a.character_ids, "text": a.text},
        hidden=True,
    )
    return {"marked": MOMENTS[a.kind], "characters": names}


class ReviewArgs(BaseModel):
    character_id: str
    approve: bool
    comment: str = Field("", max_length=2000, description="замечания игроку; при возврате — обязательно")
    secret_link: str | None = Field(
        None, max_length=2000, description="тайная связь истории героя с сюжетом, игрок её не увидит"
    )
    hook_ref: str | None = Field(
        None, description="к чему в каркасе привязать эту связь: id узла, NPC, злодея или места (если каркас есть)"
    )


@tool(
    "review_character",
    "Решение мастера по персонажу на проверке: одобрить или вернуть с комментарием.",
    ReviewArgs,
    ids={"hook_ref": "plot:hooks"},
    closes=False,
)
async def review_character(ctx: ToolContext, a: ReviewArgs) -> dict:
    ch = ctx.world.characters.get(a.character_id)
    if ch is None or ch.status != "submitted":
        raise ToolError("персонаж не на проверке")
    if not a.approve and not a.comment:
        raise ToolError("при возврате на доработку нужен комментарий")
    from app.core.campaigns import Conflict
    from app.core.characters import approve_character, record_secret_link

    before = ch.status
    if a.approve:
        await approve_character(ctx.session, ctx.campaign, ch, ctx.world.catalog)
    else:
        ch.status = "draft"
    ch.review_comment = a.comment or None
    if a.hook_ref and not a.secret_link:
        raise ToolError("hook_ref задаётся вместе с secret_link")
    if a.secret_link:
        try:
            await record_secret_link(ctx.session, ctx.campaign.id, ch, a.secret_link, ref=a.hook_ref)
        except Conflict as e:
            raise ToolError(str(e)) from e
    await ctx.record(
        "review_character",
        target_id=ch.id,
        payload={"approve": a.approve, "comment": a.comment},
        inverse=[{"table": "characters", "id": ch.id, "field": "status", "before": before}],
    )
    return {"character": ch.name, "status": ch.status}


MUTATING_FOR_NARRATION: tuple[str, ...] = ()  # в фазе повествования изменяющих инструментов нет (раздел 7.1)
READ_TOOLS = ("get_scene", "get_character", "lookup_template")


async def pending_effects_ids(ctx: ToolContext) -> list[str]:
    rows = await ctx.session.scalars(select(ActiveEffect.id).where(ActiveEffect.campaign_id == ctx.campaign.id))
    return list(rows)
