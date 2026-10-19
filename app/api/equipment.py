"""Player-controlled equipment changes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.characters import _can_manage_equipment, _view
from app.api.deps import SessionDep, UserDep
from app.content.catalog import campaign_catalog
from app.core.campaigns import AccessDenied, Conflict, get_viewer
from app.core.characters import get_character
from app.core.economy import view as economy_view
from app.core.equipment import set_equipment
from app.core.views import CharacterView, TurnEconomy
from app.core.world import load_world
from app.tools.registry import ToolError
from app.tools.runtime import flush_outbox, open_context, publish_changes

router = APIRouter(prefix="/api/campaigns/{campaign_id}", tags=["equipment"])


class EquipmentIn(BaseModel):
    inventory_id: str
    equipped: bool = True


class EquipmentResponse(BaseModel):
    character: CharacterView
    economy: TurnEconomy | None = None


@router.put("/characters/{character_id}/equipment", response_model=EquipmentResponse)
async def change_equipment(
    campaign_id: str,
    character_id: str,
    body: EquipmentIn,
    user: UserDep,
    session: SessionDep,
    request: Request,
    as_seat: str | None = None,
) -> dict:
    lock = request.app.state.master.turn_lock(campaign_id)
    if lock.locked():
        raise Conflict("мастер сейчас меняет состояние игры; повторите запрос")
    async with lock:
        viewer = await get_viewer(session, user, campaign_id, as_seat, ai_seat=False)
        ch = await get_character(session, viewer, character_id)
        if not _can_manage_equipment(viewer, ch):
            raise AccessDenied("снаряжение меняет игрок героя или его заместитель")
        if ch.status not in ("approved", "active"):
            raise Conflict("снаряжение меняют только у героя в игре")
        ctx = await open_context(
            session,
            viewer.campaign,
            request.app.state.dice_factory(),
            turn_id=None,
            seat_id=viewer.seat.id if viewer.seat else None,
        )
        try:
            await set_equipment(ctx, character_id, body.inventory_id, body.equipped)
        except ToolError as exc:
            await session.rollback()
            raise Conflict(str(exc)) from exc
        messages = await flush_outbox(session, ctx)
        await session.commit()
        cat = await campaign_catalog(session, viewer.campaign)
        world = await load_world(session, viewer.campaign, cat)
        result = {"character": await _view(session, viewer, ch), "economy": economy_view(world, character_id)}
    await publish_changes(request.app.state.bus, ctx, messages)
    return result
