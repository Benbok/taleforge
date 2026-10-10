"""Единая, не изменяющая мир проекция сцены для конкретного зрителя.

Сцена, карта и снимок WebSocket используют одни и те же правила мест и
видимости. Секреты и скрытые объекты видит только мастер; отсутствие героя
не даёт права обойти этот фильтр.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.world import PLAYABLE, party_groups, viewer_places
from app.core.world_objects import is_nested
from app.db.models import Character, Entity, Scene


@dataclass(frozen=True)
class VisibleScene:
    current_location_id: str | None
    place_ids: tuple[str, ...]
    entities: tuple[Entity, ...]
    heroes: tuple[Character, ...]
    groups: dict[str | None, list[Character]]
    is_master: bool


def visible_scene(
    scene: Scene,
    entities: dict[str, Entity],
    characters: dict[str, Character],
    *,
    hero_id: str | None,
    is_master: bool,
) -> VisibleScene:
    """Возвращает разрешённые объекты; БД и каталог не загружаются повторно.

    Для игрока — только место его активного героя; мастер и зритель без
    героя видят места всех групп, но секреты доступны только мастеру.
    """
    hero = characters.get(hero_id or "")
    if hero is not None and hero.status not in PLAYABLE:
        hero = None
    current, places = viewer_places(characters.values(), scene, None if is_master else hero)
    allowed = set(places)
    def hidden_by_sketch(e: Entity) -> bool:
        room = entities.get(e.location_id or "")
        features = ((room.state or {}).get("sketch") or {}).get("features") or [] if room is not None else []
        return any(f.get("entity_id") == e.id and f.get("hidden") for f in features)

    filtered = tuple(
        e
        for e in entities.values()
        if e.kind != "location"
        and not is_nested(e)
        and (not allowed or e.location_id in allowed)
        and (
            is_master
            or not ((e.state or {}).get("hidden") or (e.state or {}).get("secret") or hidden_by_sketch(e))
        )
    )
    heroes = tuple(
        ch
        for ch in characters.values()
        if ch.status in PLAYABLE and (not allowed or (ch.location_id or scene.location_id) in allowed)
    )
    return VisibleScene(current, tuple(places), filtered, heroes, party_groups(characters.values(), scene), is_master)
