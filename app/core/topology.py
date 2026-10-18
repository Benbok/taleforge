"""Единый источник соседства локаций для карты, эскиза и контекста мастера.

Книга определяет *куда* ведёт проход, разметка — только *где* он расположен.
Для свободной кампании сохраняются обычные links и вложенность. Resolver ничего
не создаёт и не меняет в базе; фильтрация скрытых мест выполняется у зрителя.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.content.catalog import CatalogView
from app.core.layout.contracts import Blueprint
from app.db.models import Entity


@dataclass(frozen=True)
class LocationExit:
    target_id: str | None
    room_ref: str | None
    label: str | None
    bearing: str | None
    route_id: str | None = None
    route_ref: str | None = None  # авторский географический маршрут, а не Entity-ссылка


def location_exits(
    place: Entity,
    catalog: CatalogView | None,
    entities: dict[str, Entity],
    blueprint_cache: dict[str, Blueprint | None] | None = None,
    *,
    geography=None,
) -> list[LocationExit]:
    """Соседние места; с ``geography`` добавляются авторские маршруты между конкретными участками."""
    exits = _base_exits(place, catalog, entities, blueprint_cache)
    if geography is None:
        return exits
    return [*exits, *_route_exits(place, entities, geography)]


def _route_exits(place: Entity, entities: dict[str, Entity], geography) -> list[LocationExit]:
    from app.core.geography.contracts import GeographyError
    from app.core.geography.ports import resolve_port
    from app.core.layout import store

    cx = store.complex_of(place)
    entity_id, area_ref = (cx["root_id"], cx["area_ref"]) if cx else (place.id, None)
    node = next((n for n in geography.nodes if n.entity_id == entity_id), None)
    if node is None:
        return []
    entity_ids = {n.ref: n.entity_id for n in geography.nodes if n.entity_id}
    names = {n.ref: n.name for n in geography.nodes}
    out: list[LocationExit] = []
    for link in geography.links:
        for here, there, allowed in ((link.source, link.target, True), (link.target, link.source, link.bidirectional)):
            if not allowed or here.node_ref != node.ref or here.area_ref not in (None, area_ref):
                continue
            try:
                port = resolve_port(entities, entity_ids, there)
            except GeographyError:
                continue  # непроверенный порт не подменяется соседним участком
            if port.area_id != place.id:
                out.append(LocationExit(port.area_id, None, names[there.node_ref], None, route_ref=link.ref))
    return out


def _base_exits(
    place: Entity,
    catalog: CatalogView | None,
    entities: dict[str, Entity],
    blueprint_cache: dict[str, Blueprint | None] | None = None,
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

    from app.core.layout import store

    cache = blueprint_cache if blueprint_cache is not None else {}
    cx = store.complex_of(place)
    if cx is not None:
        return [
            *_passage_exits(place, entities.get(cx["root_id"]), entities, cache),
            *_approach_exits(place, entities, cache),
        ]

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
            link
            for link in (entity.state or {}).get("links") or []
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
        if other.kind == "location" and other.location_id == place.id and not store.complex_of(other):
            add(other.id, "внутри")
    for exit_ in _approach_exits(place, entities, cache):
        add(exit_.target_id, exit_.label, exit_.bearing)
    add(place.location_id, "наружу")
    return exits


def _approach_exits(
    place: Entity,
    entities: dict[str, Entity],
    cache: dict[str, Blueprint | None],
) -> list[LocationExit]:
    """Подходы других комплексов могут выходить и в обычное место, и в участок комплекса."""
    from app.core.layout import store

    out = []
    for root in entities.values():
        bp = _blueprint(root, cache) if root.kind == "location" else None
        if bp is None:
            continue
        ids = store.area_ids(root)
        for p in bp.passages:
            if store.passage_live(root, p.passage_ref).get("hidden", p.hidden):
                continue
            for i, end in enumerate(p.ends):
                if end.external and end.place_id == place.id:
                    target = ids.get(p.ends[1 - i].area_ref or "")
                    if target and target != place.id and target in entities:
                        out.append(LocationExit(target, None, p.public_name, None))
    return out


def _blueprint(root: Entity | None, cache: dict[str, Blueprint | None]) -> Blueprint | None:
    """Кэш одного снимка мира: новое построение карты получает новый словарь."""
    from app.core.layout import store

    if root is None:
        return None
    if root.id not in cache:
        cache[root.id] = store.blueprint_of(root)
    return cache[root.id]


def _passage_exits(
    place: Entity,
    root: Entity | None,
    entities: dict[str, Entity],
    cache: dict[str, Blueprint | None],
) -> list[LocationExit]:
    """Соседи участка комплекса — только через его проходы; тайный проход соседства не даёт, пока его не нашли.
    Вложенность в корень прохода не создаёт."""
    from app.core.layout import store

    bp = _blueprint(root, cache)
    if bp is None:
        return []
    ids = store.area_ids(root)
    area_ref = store.complex_of(place)["area_ref"]
    out: list[LocationExit] = []
    for p, x in bp.ends_of(area_ref):
        if store.passage_live(root, p.passage_ref).get("hidden", p.hidden):
            continue
        o = bp.other(p, x)
        target = ids.get(o.area_ref) if o.area_ref else o.place_id
        if target and target in entities and target not in {e.target_id for e in out}:
            out.append(LocationExit(target, None, p.public_name, x.side))
    return out
