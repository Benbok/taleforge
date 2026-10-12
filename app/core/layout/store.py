"""Комплекс в мире (спецификация 2026-10-12, §4): корень хранит blueprint, реальные id участков и живое состояние
проходов; участок знает свой корень и ``area_ref``. Вложенность участка в корень показывает принадлежность, но не
создаёт прохода. Blueprint не источник текущего состояния: открыта ли дверь — ``state.passages`` корня.
"""

from __future__ import annotations

import zlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.layout.contracts import BUILDER_VERSION, Blueprint, LayoutError
from app.core.layout.intent import LayoutIntent
from app.db.models import Campaign, Entity, WorldGenerationState


def _state(e: Any) -> dict:
    return (e.state or {}) if e is not None else {}


def complex_of(e: Any) -> dict | None:
    cx = _state(e).get("complex")
    return cx if isinstance(cx, dict) and cx.get("root_id") and cx.get("area_ref") else None


def blueprint_of(root: Any) -> Blueprint | None:
    raw = _state(root).get("blueprint")
    if not isinstance(raw, dict):
        return None
    try:
        return Blueprint.from_json(raw)
    except LayoutError:
        return None


def area_ids(root: Any) -> dict[str, str]:
    return dict(_state(root).get("areas") or {})


def passage_live(root: Any, ref: str) -> dict:
    return dict((_state(root).get("passages") or {}).get(ref) or {})


def root_of(entities: dict[str, Entity], area: Any) -> Entity | None:
    cx = complex_of(area)
    return entities.get(cx["root_id"]) if cx else None


def layout_seed(campaign_id: str, root_id: str) -> int:
    return zlib.crc32(f"{campaign_id}:{root_id}:layout".encode()) & 0x7FFFFFFF


async def reserve_layout(
    session: AsyncSession, campaign: Campaign, root: Entity, intent: LayoutIntent
) -> WorldGenerationState:
    """Резерв структуры комплекса: замысел и seed фиксируются один раз; повтор возвращает ту же строку."""
    from app.core.world_generation import storage

    row = await storage.find(session, campaign.id, root.id, "location_layout")
    if row is not None:
        return row
    seed = layout_seed(campaign.id, root.id)
    reservation = {
        "phase": "location_layout",
        "seed": seed,
        "root_id": root.id,
        "plot_id": _state(root).get("plot_id"),
        "intent": intent.model_dump(mode="json"),
    }
    row = WorldGenerationState(campaign_id=campaign.id, target_entity_id=root.id, phase="location_layout",
                               status="unprepared", reservation=reservation, seed=seed,
                               generator_version=BUILDER_VERSION)  # fmt: skip
    session.add(row)
    await session.flush()
    return row


async def reserve_geometry(
    session: AsyncSession, campaign_id: str, root: Entity, area: Entity, bp: Blueprint
) -> WorldGenerationState:
    from app.core.world_generation import storage

    row = await storage.find(session, campaign_id, area.id, "location_geometry")
    if row is not None:
        return row
    cx = complex_of(area)
    reservation = {"phase": "location_geometry", "root_id": root.id, "area_ref": cx["area_ref"],
                   "blueprint_rev": bp.revision, "seed": bp.seed}  # fmt: skip
    row = WorldGenerationState(campaign_id=campaign_id, target_entity_id=area.id, phase="location_geometry",
                               status="unprepared", reservation=reservation, seed=bp.seed,
                               generator_version=BUILDER_VERSION)  # fmt: skip
    session.add(row)
    await session.flush()
    return row


async def request_geometry(ctx: Any, area: Any) -> str | None:
    """Участок комплекса без готовой геометрии: запросить её в транзакции команды. Возвращает ref, которого стоит
    дождаться; None — не участок, уже готово или заблокировано (причину читает переход)."""
    from app.core.world_generation import storage

    if complex_of(area) is None:
        return None
    row = await storage.find(ctx.session, ctx.campaign.id, area.id, "location_geometry")
    if row is None or row.status in ("ready", "blocked"):
        return None
    storage.activate(row)
    return row.id
