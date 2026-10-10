"""Единый источник соседства локаций для карты, эскиза и контекста мастера.

Книга определяет *куда* ведёт проход, разметка — только *где* он расположен.
Для свободной кампании сохраняются обычные links и вложенность. Resolver ничего
не создаёт и не меняет в базе; фильтрация скрытых мест выполняется у зрителя.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.content.catalog import CatalogView
from app.db.models import Entity


@dataclass(frozen=True)
class LocationExit:
    target_id: str | None
    room_ref: str | None
    label: str | None
    bearing: str | None


def location_exits(
    place: Entity, catalog: CatalogView | None, entities: dict[str, Entity]
) -> list[LocationExit]:
    """Соседние места; для комнаты книги допускается ещё не созданный room_ref."""
    from app.core import adventure

    ref = adventure.room_of(place)
    if ref is not None:
        # Не доверять историческим state.links у комнат книги даже тогда,
        # когда каталог недоступен или материализация соседа отложена.
        found = adventure.module_place(place, catalog, entities) if catalog is not None else None
        if found is None:
            return []
        parent, rec = found
        room = adventure.find_room(rec, str(ref["id"]))
        if room is None:
            return []
        exits: list[LocationExit] = []
        seen: set[str] = set()
        for raw in room.get("exits") or []:
            rid = str(raw)
            if rid in seen:
                continue
            neighbour = adventure.find_room(rec, rid)
            if neighbour is None:
                continue
            seen.add(rid)
            target = adventure.room_entity(entities, parent, rid)
            number = neighbour.get("number")
            label = f"Комната {number}" if number else "Неизведанная комната"
            exits.append(LocationExit(target.id if target is not None else None, rid, label, None))
        return exits

    if place.kind != "location":
        return []

    exits: list[LocationExit] = []
    seen_ids: set[str] = set()

    def add(target: str | None, label: str | None, bearing: str | None = None) -> None:
        if not target or target == place.id or target in seen_ids:
            return
        other = entities.get(target)
        if other is None or other.kind != "location":
            return
        seen_ids.add(target)
        exits.append(LocationExit(target, None, label, bearing))

    def links(entity: Entity) -> list[dict]:
        return [
            link for link in (entity.state or {}).get("links") or []
            if isinstance(link, dict) and isinstance(link.get("to"), str)
        ]

    for link in links(place):
        add(link["to"], link.get("label"), link.get("bearing"))
    for other in entities.values():
        if other.id == place.id or other.kind != "location":
            continue
        for link in links(other):
            if link["to"] == place.id:
                add(other.id, link.get("label"))
                break
    for other in entities.values():
        if other.kind == "location" and other.location_id == place.id:
            add(other.id, "внутри")
    add(place.location_id, "наружу")
    return exits
