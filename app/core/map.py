"""Схема места (просьба Arty, 2026-09-29): что герой видит вокруг и какие места отряд уже открыл.

Карта не рисуется моделью: сервер собирает её из реестра мира. Мастер влияет на неё теми же инструментами, что и
на мир: ``create_location`` (внутри чего, с чем соседствует, в какой стороне), ``link_locations``, ``move``,
``spawn_entity`` и ``add_landmark`` с зоной и стороной света. Всё, что появилось в реестре, само попадает на карту.

Два вида:

- «Вокруг» — место, где стоит герой зрителя: сущности по зонам дальности (вплотную, близко, далеко) и сторонам света,
  выходы в соседние и вложенные места;
- «Карта мест» — граф мест: где герой был (``state.visited_by``), где он сейчас и о каких местах знает
  (строка знаний, упоминание в видимом ему сообщении, соседство с местом, где он был).

Место с ``state.secret`` не видно, пока герой там не побывал или мастер не открыл его знанием. Место мастера видит
всё. Отряд, разделившись, видит каждый своё: у героя своё «здесь» (``characters.location_id``) и свои посещения.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import campaign_catalog
from app.core import adventure, map_memory, reach, sketch
from app.core.campaigns import Viewer
from app.core.inspect import entity_type, viewer_hero
from app.core.layout import store as layout_store
from app.core.map_projection import location_plan
from app.core.object_policy import concealed, revealed_to
from app.core.positions import bearing_of_cell, zone_of_cell
from app.core.preparation import container_rows, container_view
from app.core.scene_view import visible_scene
from app.core.topology import location_exits
from app.core.world import PLAYABLE, ZONE_NAMES, get_scene
from app.core.world_objects import is_nested
from app.db.models import Character, Entity, Knowledge, Message

BEARINGS = ("n", "ne", "e", "se", "s", "sw", "w", "nw")
BEARING_NAMES = {
    "n": "север",
    "ne": "северо-восток",
    "e": "восток",
    "se": "юго-восток",
    "s": "юг",
    "sw": "юго-запад",
    "w": "запад",
    "nw": "северо-запад",
}


def place_of(ch: Character, scene_location: str | None) -> str | None:
    """Где стоит герой: своё место, если его переводили отдельно, иначе место сцены."""
    return ch.location_id or scene_location


def _links(e: Entity) -> list[dict]:
    return [x for x in (e.state or {}).get("links") or [] if isinstance(x, dict) and x.get("to")]


def _condition(st: dict) -> str | None:
    if st.get("dead"):
        return "мёртв"
    hp, mx = st.get("hp"), st.get("hp_max")
    if hp is None or not mx:
        return None
    return "невредим" if hp >= mx else "ранен" if hp > mx / 2 else "тяжело ранен"


async def _mentioned_ids(session: AsyncSession, viewer: Viewer, ids: list[str]) -> set[str]:
    """Какие из мест упоминались в сообщениях, видимых зрителю (шёпот другому игроку не в счёт)."""
    if not ids:
        return set()
    q = select(Message.content, Message.visible_to).where(
        Message.campaign_id == viewer.campaign.id, Message.content.contains("[[en_")
    )
    seat = viewer.seat.id if viewer.seat else None
    out: set[str] = set()
    for content, visible_to in (await session.execute(q)).all():
        if visible_to is not None and seat not in visible_to:
            continue
        out.update(i for i in ids if f"[[{i}|" in content)
    return out


def _footprint_zones(sk: dict | None, around: list[dict], entities: dict[str, Entity], here_id: str) -> None:
    """Привязанный к эскизу объект стоит там, где его деталь: зона — от строя до ближайшей клетки footprint,
    а не сохранённая точка (docs/world-objects-delivery1.md, §2.1). Смена строя её не сбивает."""
    geometry = sketch.physical_geometry(sk, entities, here_id)
    if not geometry:
        return
    ax, ay = int(geometry["party"][0]), int(geometry["party"][1])
    for item in around:
        f = reach.feature_of(geometry, item["id"])
        if f is None:
            continue
        near = reach.nearest_rel({(c - ax, r - ay) for c, r in reach.footprint(f)})
        item["zone"] = zone_of_cell(near)
        item["zone_name"] = ZONE_NAMES.get(item["zone"], item["zone"])
        item["bearing"] = bearing_of_cell(near)
        item["cell"] = None  # одна позиция: деталь эскиза


def _in_complex(place: Entity, blueprint_cache: dict) -> bool:
    from app.core.layout import store

    if store.complex_of(place) is not None:
        return True
    if place.id not in blueprint_cache:
        blueprint_cache[place.id] = store.blueprint_of(place)
    return blueprint_cache[place.id] is not None


async def party_map(session: AsyncSession, viewer: Viewer) -> dict[str, Any]:
    cid = viewer.campaign.id
    scene = await get_scene(session, cid)
    ents = (await session.scalars(select(Entity).where(Entity.campaign_id == cid))).all()
    places = {e.id: e for e in ents if e.kind == "location"}
    blueprint_cache = {}
    master = viewer.seat is not None and viewer.seat.role == "master"
    hero = None if master else await viewer_hero(session, viewer)

    q = select(Character).where(Character.campaign_id == cid)
    all_chars = {ch.id: ch for ch in (await session.scalars(q)).all()}
    revealed = await revealed_to(session, hero.id if hero is not None else None)
    view = visible_scene(
        scene,
        {e.id: e for e in ents},
        all_chars,
        hero_id=hero.id if hero is not None else None,
        is_master=master,
        revealed=revealed,
    )
    heroes = [hero] if hero is not None and hero.status in PLAYABLE else list(view.heroes)
    here_id = view.current_location_id
    hero_ids = {h.id for h in heroes}
    heres = {place_of(h, scene.location_id) for h in heroes} | {here_id}
    allowed_entities = {e.id for e in view.entities}

    visited = {
        pid for pid, p in places.items() if pid in heres or hero_ids & set((p.state or {}).get("visited_by") or [])
    }
    has_book_rooms = any(adventure.room_of(p) for p in places.values())
    catalog = await campaign_catalog(session, viewer.campaign) if has_book_rooms else None
    if master:
        shown = set(places)
    else:
        shown = set(visited)
        if hero_ids:
            q = select(Knowledge.entity_id).where(Knowledge.character_id.in_(hero_ids))
            shown |= {i for i in (await session.scalars(q)).all() if i in places}
        shown |= await _mentioned_ids(session, viewer, [i for i in places if i not in shown])
        # из места, где побывали, видно, внутри чего оно, что в нём и куда из него ведут пути
        for pid in list(visited):
            p = places[pid]
            near = {x.target_id for x in location_exits(p, catalog, places, blueprint_cache) if x.target_id}
            if p.location_id:
                near.add(p.location_id)  # группировка; не выход из комнаты книги
            shown |= {n for n in near if n in places and not (places[n].state or {}).get("secret")}

    if hero is not None:
        opened = await map_memory.opened_areas(session, hero.id)
        shown = {pid for pid in shown if not layout_store.complex_of(places[pid]) or pid in opened or pid == here_id}
        shown |= {pid for pid in opened if pid in places}

    def status(pid: str) -> str:
        if pid == here_id:
            return "here"
        return "visited" if pid in visited else "known"

    out_places = [
        {
            "id": p.id,
            "name": p.name if master else adventure.public_name(p, p.id in visited),
            "parent_id": p.location_id if p.location_id in shown else None,
            "status": status(p.id),
        }
        for p in sorted((places[i] for i in shown), key=lambda e: (e.created_at or 0, e.id))  # id — при равном времени
    ]
    here = places.get(here_id or "")
    # В модуле настоящие переходы между комнатами определены книгой.
    # state.links может содержать старые ссылки, добавленные при перемещениях.
    has_book_rooms = any(adventure.room_of(places[pid]) for pid in shown)
    if catalog is None and here is not None and here.template_id:
        catalog = await campaign_catalog(session, viewer.campaign)
    book_destinations: dict[str, set[str]] = {}
    if catalog is not None and has_book_rooms:
        for pid in shown:
            destinations = adventure.room_destinations(places[pid], catalog, places)
            if destinations is not None:
                book_destinations[pid] = destinations

    links, seen = [], set()
    for pid in shown:
        for x in _links(places[pid]):
            other = x["to"]
            forward = book_destinations.get(pid)
            reverse = book_destinations.get(other)
            if (forward is not None or reverse is not None) and (
                other not in (forward or set()) and pid not in (reverse or set())
            ):
                continue
            key = tuple(sorted((pid, other)))
            if x["to"] in shown and key not in seen:
                seen.add(key)
                links.append({"a": key[0], "b": key[1], "label": x.get("label")})

    # Книга даёт соседство независимо от исторических state.links.
    for src, targets in book_destinations.items():
        for dst in targets:
            if dst not in shown:
                continue
            key = tuple(sorted((src, dst)))
            if key not in seen:
                seen.add(key)
                links.append({"a": key[0], "b": key[1], "label": None})

    around: list[dict] = []
    exits: list[dict] = []
    party: list[dict] = []
    areas: list[dict] = []
    if here is not None:
        by_id = {e.id: e for e in ents}
        boxes = await container_rows(session, cid)
        for e in ents:
            if e.id not in allowed_entities or e.location_id != here.id or is_nested(e):
                continue
            st = e.state or {}
            if not master and concealed(e, by_id, revealed):
                continue  # тайное само, тайная деталь эскиза: ни в одном поле ответа игроку
            area = st.get("area")
            if area:
                if area.get("expires_at") is None or scene.game_time < int(area["expires_at"]):
                    areas.append(
                        {
                            "id": e.id,
                            "name": e.name,
                            "zone": e.zone,
                            "bearing": st.get("bearing"),
                            "radius_ft": int(area.get("radius_ft", 10)),
                        }
                    )
                continue
            item = {
                "id": e.id,
                "name": e.name,
                "type": entity_type(e),
                "visual_key": st.get("visual_key") if isinstance(st.get("visual_key"), str) else None,
                "zone": e.zone,
                "zone_name": ZONE_NAMES.get(e.zone, e.zone),
                "bearing": st.get("bearing"),
                "elevation": st.get("elevation") or "ground",
                "cover": st.get("cover") or "none",
                "cell": st.get("cell"),  # клетка от строя отряда, если мастер поставил точно
            }
            if e.kind == "creature":
                item["condition"] = _condition(st)
                companion = st.get("companion")
                if isinstance(companion, dict) and isinstance(companion.get("of"), str):
                    item["companion_of"] = companion["of"]
            box = container_view(e, boxes) if e.kind == "object" else None
            if box is not None:
                item["container"] = box
            around.append(item)
        # герои в этом месте: у кого нет позиции, тот в строю отряда, в центре схемы
        positions = (scene.state or {}).get("positions") or {}
        for ch in all_chars.values():
            if ch.status not in PLAYABLE:
                continue
            if place_of(ch, scene.location_id) != here.id:
                continue
            pos = positions.get(ch.id) or {}
            party.append(
                {
                    "id": ch.id,
                    "name": ch.name,
                    "mine": hero is not None and ch.id == hero.id,
                    "zone": pos.get("zone"),
                    "bearing": pos.get("bearing"),
                    "elevation": pos.get("elevation") or "ground",
                    "cover": pos.get("cover") or "none",
                    "cell": pos.get("cell"),
                    "down": (ch.resources or {}).get("hp") == 0,
                }
            )
        for p in out_places:
            pid = p["id"]
            if pid == here.id:
                continue
            if here.id in book_destinations and pid not in book_destinations[here.id]:
                continue
            link = next((x for x in _links(here) if x["to"] == pid), None)
            back = next((x for x in _links(places[pid]) if x["to"] == here.id), None)
            if _in_complex(here, blueprint_cache) or _in_complex(places[pid], blueprint_cache):
                # комплекс: соседи и подписи — по проходам blueprint; вложенность и старые links прохода не дают
                found = next(
                    (x for x in location_exits(here, catalog, places, blueprint_cache) if x.target_id == pid), None
                )
                if found is None:
                    continue
                link = {"bearing": found.bearing}
                via = found.label
            elif link or back:
                via = (link or back).get("label")
            elif places[pid].location_id == here.id:
                via = "внутри"
            elif here.location_id == pid:
                via = "наружу"
            else:
                continue
            exits.append(
                {
                    "id": pid,
                    "room_ref": next(
                        (
                            x.room_ref
                            for x in location_exits(here, catalog, places, blueprint_cache)
                            if x.target_id == pid
                        ),
                        None,
                    ),
                    "name": p["name"],
                    "via": via,
                    "bearing": (link or {}).get("bearing") or (places[pid].state or {}).get("bearing"),
                    "visited": p["status"] != "known",
                }
            )
    if here is not None and adventure.room_of(here) and catalog is not None:
        known_ids = {exit["id"] for exit in exits}
        for passage in location_exits(here, catalog, places, blueprint_cache):
            if passage.target_id is not None and passage.target_id not in shown:
                continue
            if passage.target_id is not None and passage.target_id in known_ids:
                continue
            if passage.room_ref:
                known_ids.add(passage.target_id)
                exits.append(
                    {
                        "id": passage.target_id,
                        "name": next((p["name"] for p in out_places if p["id"] == passage.target_id), passage.label),
                        "room_ref": passage.room_ref,
                        "via": None,
                        "bearing": passage.bearing,
                        "visited": passage.target_id in visited,
                    }
                )
    if here is not None:
        _footprint_zones(sketch.of_place(here, catalog, places), around, {e.id: e for e in ents}, here.id)

    # The book receives unmodified scene tokens; Around renders bound Entity as a sketch feature.
    scene_view = [
        {
            "id": h["id"],
            "name": h["name"],
            "type": "hero",
            "mine": h["mine"],
            "down": h["down"],
            "zone": h["zone"],
            "bearing": h["bearing"],
            "cell": h["cell"],
        }
        for h in party
    ] + [
        {
            "id": t["id"],
            "name": t["name"],
            "type": t["type"],
            "visual_key": t.get("visual_key"),
            "mine": False,
            "down": t.get("condition") == "мёртв",
            "zone": t["zone"],
            "bearing": t["bearing"],
            "cell": t["cell"],
            "companion_of": t.get("companion_of"),
        }
        for t in around
    ]
    book = sk = None
    if here is not None and (here.template_id or adventure.room_of(here)):  # карта книги — только у мест модуля
        if catalog is None:
            catalog = await campaign_catalog(session, viewer.campaign)
        positions = (scene.state or {}).get("positions") or {}
        heroes_at = [
            (ch, place_of(ch, scene.location_id), positions.get(ch.id) or {})
            for ch in all_chars.values()
            if ch.status in PLAYABLE
        ]
        book = adventure.book_map(
            catalog,
            places,
            here,
            heroes_at,
            None if master else visited,
            hero.id if hero is not None else None,
            entities=ents,
            scene_tokens=scene_view,
        )
        sk = sketch.of_place(here, catalog, places)
    else:
        sk = sketch.of_place(here, None, places) if here is not None and (here.state or {}).get("sketch") else None
    projected_sketch = (
        sketch.project_for_viewer(sk, master, shown, {e.id: e for e in ents}, here.id, revealed)
        if sk and here
        else None
    )
    if projected_sketch is not None:
        projected_sketch["placement_rev"] = int((here.state or {}).get("placement_rev") or 0)
    linked = sketch.linked_entity_ids(projected_sketch)
    scene_view = [token for token in scene_view if token["id"] not in linked]
    location_map = await location_plan(
        session, hero if not master else None, {e.id: e for e in ents}, here_id, blueprint_cache
    )
    if here is not None:
        grants = await map_memory.known_passages(session, hero.id, here.id) if hero else frozenset()
        visible_refs = set()
        passage_exits = []
        for root in places.values():
            if root.id not in blueprint_cache:
                blueprint_cache[root.id] = layout_store.blueprint_of(root)
            bp = blueprint_cache[root.id]
            if bp is None:
                continue
            ids = layout_store.area_ids(root)
            for p in bp.passages:
                if not master and p.hidden and (root.id, p.passage_ref) not in grants:
                    continue
                live = layout_store.passage_live(root, p.passage_ref)
                for index, end in enumerate(p.ends):
                    source = ids.get(end.area_ref) if end.area_ref else end.place_id
                    if source != here.id:
                        continue
                    other = p.ends[1 - index]
                    target = ids.get(other.area_ref) if other.area_ref else other.place_id
                    visible_refs.add(p.passage_ref)
                    known = target in shown
                    passage_exits.append(
                        {
                            "id": target if known else None,
                            "room_ref": None,
                            "name": places[target].name if known else p.public_name,
                            "via": p.public_name,
                            "bearing": end.side,
                            "visited": target in visited,
                            "passage_ref": p.passage_ref,
                            "kind": p.kind,
                            "state": live.get("state", p.state),
                            "width": end.width,
                            "cells": next(
                                (
                                    x.get("cells")
                                    for x in (sk or {}).get("exits", [])
                                    if x.get("passage_ref") == p.passage_ref
                                ),
                                None,
                            ),
                        }
                    )
        if projected_sketch is not None:
            projected_sketch["exits"] = [
                x
                for x in projected_sketch.get("exits", [])
                if not x.get("passage_ref") or x["passage_ref"] in visible_refs
            ]
        if passage_exits:
            exits = [x for x in exits if not x.get("id") or not layout_store.complex_of(places[x["id"]])]
            exits.extend(passage_exits)
    return {
        "book": book,
        "sketch": projected_sketch,
        "here": {
            "id": here.id,
            "name": here.name,
            "description": adventure.public_description(here, catalog)
            if adventure.room_of(here)
            else here.description or None,
        }
        if here
        else None,
        "around": around,
        "scene_view": scene_view,
        "party": party,
        "areas": areas,
        "mode": scene.mode,
        "exits": exits,
        "places": out_places,
        "links": links,
        "bearings": BEARING_NAMES,
        "location_map": location_map,
    }
