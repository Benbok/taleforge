"""Record the physical constraints of a transformation already allowed by its rules."""

import copy

from pydantic import BaseModel, Field

from app.core.character_form import current_form
from app.tools.master.base import _character
from app.tools.registry import ToolContext, tool


class SetCharacterFormArgs(BaseModel):
    character_id: str
    name: str | None = Field(..., min_length=1, max_length=120, description="физический облик; null — свой облик")
    can_handle_items: bool = Field(
        False, description="может ли тело брать и передавать снаряжение; у крысы без рук — false"
    )
    duration_seconds: int | None = Field(None, ge=1, description="оставшееся время облика, если оно ограничено")
    reason: str = Field(min_length=3, max_length=300, description="какое подтверждённое превращение или возврат")


@tool(
    "set_character_form",
    "Фиксирует текущий физический облик и возможность обращаться со снаряжением. Вызывай после разрешённого "
    "превращения или возврата, до описания успеха. Не даёт способности превращаться, не списывает её цену "
    "и не меняет боевые характеристики: сначала исполни правило/заклинание/умение. Иллюзия не меняет тело. "
    "name=null возвращает свой облик; не возвращай его автоматически ради подбора предмета.",
    SetCharacterFormArgs,
    ids={"character_id": "characters"},
    closes=False,
)
async def set_character_form(ctx: ToolContext, a: SetCharacterFormArgs) -> dict:
    ch = _character(ctx, a.character_id)
    before = copy.deepcopy(ch.resources)
    resources = dict(ch.resources or {})
    if a.name is None:
        resources.pop("current_form", None)
    else:
        resources["current_form"] = {
            "name": a.name,
            "can_handle_items": a.can_handle_items,
            "reason": a.reason,
            "expires_at": ctx.world.scene.game_time + a.duration_seconds if a.duration_seconds else None,
        }
    ch.resources = resources
    ctx.world.invalidate(ch.id)
    result = {"character": ch.name, "current_form": current_form(ch, ctx.world.scene.game_time)}
    await ctx.record(
        "set_character_form",
        actor_id=ch.id,
        payload=result,
        inverse=[{"table": "characters", "id": ch.id, "field": "resources", "before": before}],
    )
    return result
