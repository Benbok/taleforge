"""Квитанции и статус подготовки мира (спецификация генерации сцен, §6.1; docs/world-objects-delivery2.md).

Команда, требующая подготовки, сохраняет в ``Event`` неизменяемую квитанцию ``{accepted: true, operation_ref}``.
``operation_ref`` — id ``WorldGenerationState``: идентичность подготовки, а не команды игрока. Живой статус
читается отдельно и ничего не запускает:

- ``unexamined`` — резерв без ``requested_at``: никто ещё не попросил;
- ``pending`` — запрошено (``unprepared`` с ``requested_at``) или готовится (``preparing``);
- ``ready`` — результат сохранён; ``blocked`` — диагностируемая проблема, причина в ``reason``.

Доступ проверяет кампанию и право видеть цель; знание ``operation_ref`` доступа не даёт.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.campaigns import NotFound
from app.core.object_policy import concealed, revealed_to
from app.core.world_objects import read_world_object
from app.db.models import Character, Entity, Knowledge, Scene, WorldGenerationState

PUBLIC = {"unprepared": "pending", "preparing": "pending", "ready": "ready", "blocked": "blocked"}


def receipt(operation_ref: str) -> dict[str, Any]:
    return {"accepted": True, "operation_ref": operation_ref}


def public_status(row: WorldGenerationState) -> str:
    if row.status == "unprepared" and row.requested_at is None:
        return "unexamined"
    return PUBLIC.get(row.status, "blocked")


def _brief(row: WorldGenerationState) -> dict[str, Any]:
    status = public_status(row)
    return {
        "operation_ref": row.id,
        "status": status,
        "revision": row.revision,
        "quality": row.quality,
        "reason": row.last_error if status == "blocked" else None,
    }


async def brief_status(session: AsyncSession, campaign_id: str, operation_ref: str) -> dict[str, Any]:
    """Статус для мастера и восстановителя, без проекции. Чужой или неизвестный ref — ``unknown``."""
    row = await session.get(WorldGenerationState, operation_ref)
    if row is None or row.campaign_id != campaign_id:
        return {"operation_ref": operation_ref, "status": "unknown"}
    return _brief(row)


def _generated_by(entity: Entity, ref: str) -> bool:
    if entity.kind != "object":
        return False
    raw = (entity.state or {}).get("world_object") if isinstance(entity.state, dict) else None
    if isinstance(raw, dict) and raw.get("generation_ref") == ref:
        return True
    try:
        return read_world_object(entity).metadata.get("generation_ref") == ref
    except ValueError:
        return False


async def generation_status(
    session: AsyncSession, campaign_id: str, operation_ref: str, heroes: list[Character] | None
) -> dict[str, Any]:
    """Статус подготовки для зрителя. ``heroes`` — его герои; None — мастер, ему видно всё.

    После ``ready`` — проекция: созданные подготовкой объекты, видимые хотя бы одному герою зрителя."""
    row = await session.get(WorldGenerationState, operation_ref)
    if row is None or row.campaign_id != campaign_id:
        raise NotFound("подготовка не найдена")
    entities = {e.id: e for e in await session.scalars(select(Entity).where(Entity.campaign_id == campaign_id))}
    sight = None if heroes is None else await _sight(session, campaign_id, heroes, entities)
    target = entities.get(row.target_entity_id)
    if target is None or (sight is not None and not sight(target)):
        raise NotFound("подготовка не найдена")
    out = _brief(row) | {"target_id": target.id, "phase": row.phase}
    if out["status"] == "ready":
        made = [e for e in entities.values() if _generated_by(e, row.id) and (sight is None or sight(e))]
        out["objects"] = [{"id": e.id, "name": e.name} for e in sorted(made, key=lambda e: e.id)]
    return out


async def _sight(session: AsyncSession, campaign_id: str, heroes: list[Character], entities: dict[str, Entity]):
    """Видит ли хотя бы один герой объект: по общей policy, в своём месте или по памяти о нём."""
    from app.core.world import PLAYABLE

    live = [h for h in heroes if h.status in PLAYABLE]
    found = {h.id: await revealed_to(session, h.id) for h in live}
    known = set()
    if live:
        q = select(Knowledge.entity_id).where(Knowledge.character_id.in_([h.id for h in live]))
        known = set((await session.scalars(q)).all())

    scene = await session.get(Scene, campaign_id)  # только чтение: get_scene создал бы строку сцены
    scene_place = scene.location_id if scene is not None else None

    def place_of(hero: Character) -> str | None:
        return hero.location_id or scene_place

    def sees(entity: Entity) -> bool:
        for hero in live:
            if concealed(entity, entities, found[hero.id]):
                continue
            here = entity.location_id or entity.id
            if entity.id in known or here == place_of(hero) or entity.id == place_of(hero):
                return True
        return False

    return sees
