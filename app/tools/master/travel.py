"""Master tool: travel along an authored route between concrete areas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.geography.travel import travel_route
from app.tools.registry import ToolContext, ToolError, tool


class TravelRouteArgs(BaseModel):
    route_id: str = Field(min_length=1, description="маршрут из списка доступных направлений текущего места")
    character_ids: list[str] = Field(min_length=1)


@tool(
    "travel_route",
    "Переводит героев по авторскому маршруту в участок назначения. Маршрут выбираете вы по route_id; "
    "обратный путь или соседний выход его не заменяют.",
    TravelRouteArgs,
    ids={"character_ids": "characters"},
)
async def travel_route_tool(ctx: ToolContext, a: TravelRouteArgs) -> dict:
    result = await travel_route(ctx, a.route_id, a.character_ids)
    if result.failure_code:
        raise ToolError(f"переход не выполнен: {result.failure_code}")  # no one moved
    return result.model_dump()
