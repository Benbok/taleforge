"""Подготовка мира и граница хода (спецификация генерации сцен, §6.1, §6.4; docs/world-objects-delivery2.md):
статус подготовки по квитанции и повтор описания хода, у которого оно не удалось."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.deps import SessionDep, UserDep
from app.core import campaigns as svc
from app.core import preparation
from app.core.campaigns import AccessDenied, Conflict
from app.core.inspect import viewer_hero

router = APIRouter(prefix="/api", tags=["generation"])


class GeneratedObject(BaseModel):
    id: str
    name: str


class GenerationStatusOut(BaseModel):
    operation_ref: str
    status: Literal["unexamined", "pending", "ready", "blocked"]
    revision: int
    quality: str | None = None
    reason: str | None = None
    target_id: str
    phase: str
    objects: list[GeneratedObject] | None = None


class NarrationRetryOut(BaseModel):
    accepted: bool


class OrientationMapIn(BaseModel):
    location_id: str = Field(min_length=1, max_length=32)


class OrientationMapOut(BaseModel):
    created: bool
    location_id: str


@router.post("/campaigns/{campaign_id}/orientation-map", response_model=OrientationMapOut)
async def orientation_map(
    campaign_id: str, body: OrientationMapIn, user: UserDep, session: SessionDep,
    request: Request, as_seat: str | None = None,
) -> dict:
    from app.core.universal.orientation_generation import generate_for_viewer
    from app.gateway.events import envelope

    viewer = await svc.get_viewer(session, user, campaign_id, as_seat, ai_seat=True)
    try:
        result = await generate_for_viewer(session, viewer, body.location_id)
    except ValueError as exc:
        raise Conflict(str(exc)) from exc
    await session.commit()
    if result["created"]:
        await request.app.state.bus.publish(campaign_id, envelope("map.changed", campaign_id, {}), None)
    return result


@router.get("/campaigns/{campaign_id}/generation/{operation_ref}", response_model=GenerationStatusOut)
async def generation_status(campaign_id: str, operation_ref: str, user: UserDep, session: SessionDep) -> dict:
    """Только чтение: ничего не ставит в очередь. Мастер видит всё, игрок — только то, что видит его герой."""
    viewer = await svc.get_viewer(session, user, campaign_id)
    if viewer.is_master or (viewer.is_owner and viewer.seat is None):
        heroes = None  # мастер и владелец без места видят всё, как журнал мастера
    else:
        hero = await viewer_hero(session, viewer)
        heroes = [hero] if hero is not None else []
    return await preparation.generation_status(session, campaign_id, operation_ref, heroes)


@router.post("/campaigns/{campaign_id}/turns/{turn_id}/narration", response_model=NarrationRetryOut)
async def retry_narration(campaign_id: str, turn_id: str, user: UserDep, session: SessionDep, request: Request) -> dict:
    """Повтор описания хода, действия которого сохранены, а описание не удалось: тот же id сообщения."""
    viewer = await svc.get_viewer(session, user, campaign_id)
    if not (viewer.is_owner or viewer.is_master):
        raise AccessDenied("повторить описание может владелец или мастер")
    await session.rollback()
    if not await request.app.state.master.reopen_narration(campaign_id, turn_id):
        raise Conflict("описание этого хода повторить нельзя")
    return {"accepted": True}
