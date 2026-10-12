"""REST API для каталога и страниц детализации миров."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import OptionalUserDep, SessionDep
from app.core import worlds as svc
from app.core.worlds import WorldDetail, WorldSummary

router = APIRouter(prefix="/api/worlds", tags=["worlds"])


@router.get("", response_model=list[WorldSummary])
async def list_worlds(session: SessionDep, user: OptionalUserDep = None) -> list[WorldSummary]:
    """Список всех доступных миров и правил."""
    return await svc.list_worlds(session)


@router.get("/{world_id}", response_model=WorldDetail)
async def get_world(world_id: str, session: SessionDep, user: OptionalUserDep = None) -> WorldDetail:
    """Подробная информация о мире: лор, фракции, локации, классы, происхождения, шкалы, бестиарий."""
    return await svc.get_world_detail(session, world_id)
