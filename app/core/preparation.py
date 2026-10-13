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


async def container_rows(session: AsyncSession, campaign_id: str) -> dict[str, WorldGenerationState]:
    """Строки подготовки содержимого контейнеров кампании: цель → строка."""
    q = select(WorldGenerationState).where(
        WorldGenerationState.campaign_id == campaign_id, WorldGenerationState.phase == "container_contents"
    )
    return {r.target_entity_id: r for r in await session.scalars(q)}


def container_view(entity: Entity, rows: dict[str, WorldGenerationState]) -> dict[str, Any] | None:
    """Что зритель видит о контейнере (поставка 6): открыт ли, заперт ли и состояние содержимого —
    ``unexamined`` (не исследован), ``pending`` (готовится), ``ready`` или ``blocked``. Без строки подготовки
    содержимое готово: ручной или старый контейнер читается как есть."""
    try:
        view = read_world_object(entity)
    except ValueError:
        return None
    if view.role != "container" or view.metadata.get("physical") == "destroyed":
        return None
    access = view.metadata.get("access") or {}
    row = rows.get(entity.id)
    return {
        "open": bool(access.get("open")),
        "locked": bool(access.get("locked")),
        "contents": public_status(row) if row is not None else "ready",
    }


async def preserve_seen_places(session: AsyncSession, campaign_id: str) -> int:
    """Явное включение генерации (§8.3, поставка 6): места, где отряд уже был, фиксируются
    ``ready/legacy_preserved`` и не наполняются задним числом. Ещё не посещённые места получат резерв при входе.
    Вызывается в транзакции записи мира; возвращает, сколько мест зафиксировано."""
    from app.core.world_generation.contracts import POLICY_VERSION
    from app.core.world_tx import world_write
    from app.db.models import now

    have = set(
        await session.scalars(
            select(WorldGenerationState.target_entity_id).where(
                WorldGenerationState.campaign_id == campaign_id, WorldGenerationState.phase == "location_initial"
            )
        )
    )
    places = await session.scalars(select(Entity).where(Entity.campaign_id == campaign_id, Entity.kind == "location"))
    heroes = await session.scalars(select(Character.location_id).where(Character.campaign_id == campaign_id))
    scene = await session.get(Scene, campaign_id)
    here = {p for p in heroes if p} | ({scene.location_id} if scene is not None and scene.location_id else set())
    seen = [p for p in places if p.id not in have and (p.id in here or (p.state or {}).get("visited_by"))]
    if not seen:
        return 0
    await world_write(session, campaign_id)
    t = now()
    for p in seen:
        session.add(
            WorldGenerationState(
                campaign_id=campaign_id,
                target_entity_id=p.id,
                phase="location_initial",
                status="ready",
                quality="legacy_preserved",
                generator_version=POLICY_VERSION,
                completed_at=t,
                result_manifest={"objects": [], "notes": ["legacy_preserved"]},
            )
        )
    return len(seen)


def _bucket() -> dict[str, Any]:
    return {
        "rows": 0,
        "ready": 0,
        "pending": 0,
        "blocked": 0,
        "calls": 0,
        "errors": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "tokens_reasoning": 0,
        "cost": 0.0,
        "duration_ms": 0,
    }


async def location_cost(session: AsyncSession, campaign_id: str, root_id: str) -> dict[str, Any]:
    """Расходы подготовки места по фазам (спецификация 2026-10-12, §8): структура, геометрия участков, обстановка
    и содержимое контейнеров в них; вызовы модели — по ``LlmCall.generation_id``, включая отклонённые ответы и
    токены рассуждений. Длительность фазы — от запроса до готовности. Только чтение."""
    from app.core.layout import store
    from app.db.models import LlmCall, as_utc

    root = await session.get(Entity, root_id)
    if root is None or root.campaign_id != campaign_id or root.kind != "location":
        raise NotFound("место не найдено")
    places = [root.id, *store.area_ids(root).values()]
    containers = list(
        await session.scalars(
            select(Entity.id).where(
                Entity.campaign_id == campaign_id, Entity.location_id.in_(places), Entity.kind == "object"
            )
        )
    )
    q = select(WorldGenerationState).where(
        WorldGenerationState.campaign_id == campaign_id,
        WorldGenerationState.target_entity_id.in_(places + containers),
    )
    found = {r.id: r for r in await session.scalars(q)}
    phases: dict[str, dict[str, Any]] = {}
    for r in found.values():
        b = phases.setdefault(r.phase, _bucket())
        b["rows"] += 1
        status = public_status(r)
        b[{"ready": "ready", "blocked": "blocked"}.get(status, "pending")] += 1
        if r.requested_at is not None and r.completed_at is not None:
            b["duration_ms"] += max(0, int((as_utc(r.completed_at) - as_utc(r.requested_at)).total_seconds() * 1000))
    if found:
        for c in await session.scalars(select(LlmCall).where(LlmCall.generation_id.in_(list(found)))):
            b = phases[found[c.generation_id].phase]
            b["calls"] += 1
            b["errors"] += 1 if c.error else 0
            b["tokens_in"] += c.tokens_in or 0
            b["tokens_out"] += c.tokens_out or 0
            b["tokens_reasoning"] += c.tokens_reasoning or 0
            b["cost"] += c.cost or 0.0
    total = _bucket()
    for b in phases.values():
        for k in total:
            total[k] += b[k]
    return {"root_id": root.id, "phases": phases, "total": total}
