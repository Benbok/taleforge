"""Совместимое чтение Entity.state.world_object без миграции старых сцен.

Этот адаптер намеренно не заполняет state при чтении и не изменяет visual_key:
пока операции переноса/контейнеров не реализованы, legacy предметы остаются как есть.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Literal

from app.db.models import Entity

WorldRole = Literal["item", "prop", "container"]
_ROLES = {"item", "prop", "container"}


@dataclass(frozen=True)
class WorldObjectView:
    schema_version: int | None
    legacy: bool
    role: WorldRole
    unique: bool
    container_id: str | None
    revision: int
    capabilities: frozenset[str]
    visual_key: str | None
    metadata: dict[str, Any]


def read_world_object(entity: Entity) -> WorldObjectView:
    """Прочесть физический объект, сохраняя старые state.item / state.landmark / visual_key."""
    if entity.kind != "object":
        raise ValueError("world_object доступен только для Entity.kind='object'")

    state = entity.state if isinstance(entity.state, dict) else {}
    key = state.get("visual_key")
    visual_key = key if isinstance(key, str) else None
    raw = state.get("world_object")
    if raw is None:
        return WorldObjectView(
            schema_version=None,
            legacy=True,
            role="item" if state.get("item") else "prop",
            unique=False,
            container_id=None,
            revision=0,
            capabilities=frozenset(),
            visual_key=visual_key,
            metadata={},
        )
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("неподдерживаемая версия Entity.state.world_object")

    role = raw.get("role")
    if role not in _ROLES:
        raise ValueError("неверная роль World Object")
    unique = raw.get("unique", False)
    container_id = raw.get("container_id")
    revision = raw.get("revision", 0)
    capabilities = raw.get("capabilities", [])
    if not isinstance(unique, bool):
        raise ValueError("unique должен быть логическим значением")
    if container_id is not None and (not isinstance(container_id, str) or not container_id):
        raise ValueError("container_id должен быть непустой строкой")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("revision должен быть неотрицательным целым")
    if not isinstance(capabilities, list) or any(not isinstance(c, str) for c in capabilities):
        raise ValueError("capabilities должен быть списком строк")

    return WorldObjectView(
        schema_version=1,
        legacy=False,
        role=role,
        unique=unique,
        container_id=container_id,
        revision=revision,
        capabilities=frozenset(capabilities),
        visual_key=visual_key,
        metadata=copy.deepcopy(raw),
    )
