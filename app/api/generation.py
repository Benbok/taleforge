"""Подготовка мира и граница хода (спецификация генерации сцен, §6.1, §6.4; docs/world-objects-delivery2.md):
статус подготовки по квитанции и повтор описания хода, у которого оно не удалось."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

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
