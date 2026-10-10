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
from app.core import adventure, sketch
from app.core.campaigns import Viewer
from app.core.inspect import entity_type, viewer_hero
from app.core.world import PLAYABLE, ZONE_NAMES, get_scene
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


async def party_map(session: AsyncSession, viewer: Viewer) -> dict[str, Any]:
    cid = viewer.campaign.id
    scene = await get_scene(session, cid)
    ents = (await session.scalars(select(Entity).where(Entity.campaign_id == cid))).all()
    places = {e.id: e for e in ents if e.kind == "location"}
    master = viewer.seat is not None and viewer.seat.role == "master"
    hero = None if master else await viewer_hero(session, viewer)

    if hero is not None:
        heroes = [hero]
        here_id = place_of(hero, scene.location_id)
    else:
        q = select(Character).where(Character.campaign_id == cid, Character.status.in_(PLAYABLE))
        heroes = list((await session.scalars(q)).all())
        here_id = scene.location_id
    hero_ids = {h.id for h in heroes}
    heres = {place_of(h, scene.location_id) for h in heroes} | {here_id}

    visited = {
        pid for pid, p in places.items() if pid in heres or hero_ids & set((p.state or {}).get("visited_by") or [])
    }
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
            near = {x["to"] for x in _links(p)} | {c for c, e in places.items() if e.location_id == pid}
            if p.location_id:
                near.add(p.location_id)
            for oid, o in places.items():
                if any(x["to"] == pid for x in _links(o)):
                    near.add(oid)
            shown |= {n for n in near if n in places and not (places[n].state or {}).get("secret")}

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
        for p in sorted((places[i] for i in shown), key=lambda e: e.created_at or 0)
    ]
    links, seen = [], set()
    for pid in shown:
        for x in _links(places[pid]):
            key = tuple(sorted((pid, x["to"])))
            if x["to"] in shown and key not in seen:
                seen.add(key)
                links.append({"a": key[0], "b": key[1], "label": x.get("label")})

    here = places.get(here_id or "")
    around: list[dict] = []
    exits: list[dict] = []
    party: list[dict] = []
    areas: list[dict] = []
    if here is not None:
        for e in ents:
            if e.kind == "location" or e.location_id != here.id:
                continue
            st = e.state or {}
            if not master and (st.get("hidden") or st.get("secret")):
                continue
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
                "zone": e.zone,
                "zone_name": ZONE_NAMES.get(e.zone, e.zone),
                "bearing": st.get("bearing"),
                "elevation": st.get("elevation") or "ground",
                "cover": st.get("cover") or "none",
                "cell": st.get("cell"),  # клетка от строя отряда, если мастер поставил точно
            }
            if e.kind == "creature":
                item["condition"] = _condition(st)
            around.append(item)
        # герои в этом месте: у кого нет позиции, тот в строю отряда, в центре схемы
        positions = (scene.state or {}).get("positions") or {}
        q = select(Character).where(Character.campaign_id == cid, Character.status.in_(PLAYABLE))
        for ch in (await session.scalars(q)).all():
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
            link = next((x for x in _links(here) if x["to"] == pid), None)
            back = next((x for x in _links(places[pid]) if x["to"] == here.id), None)
            if link or back:
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
                    "name": p["name"],
                    "via": via,
                    "bearing": (link or {}).get("bearing") or (places[pid].state or {}).get("bearing"),
                    "visited": p["status"] != "known",
                }
            )
    # Единый, уже отфильтрованный для зрителя список маркеров сцены.
    scene_view = [
        {"id": h["id"], "name": h["name"], "type": "hero", "mine": h["mine"], "down": h["down"],
         "zone": h["zone"], "bearing": h["bearing"], "cell": h["cell"]}
        for h in party
    ] + [
        {"id": t["id"], "name": t["name"], "type": t["type"], "mine": False,
         "down": t.get("condition") == "мёртв", "zone": t["zone"],
         "bearing": t["bearing"], "cell": t["cell"]}
        for t in around
    ]
    book = sk = None
    if here is not None and (here.template_id or adventure.room_of(here)):  # карта книги — только у мест модуля
        catalog = await campaign_catalog(session, viewer.campaign)
        positions = (scene.state or {}).get("positions") or {}
        q = select(Character).where(Character.campaign_id == cid, Character.status.in_(PLAYABLE))
        heroes_at = [
            (ch, place_of(ch, scene.location_id), positions.get(ch.id) or {}) for ch in (await session.scalars(q)).all()
        ]
        book = adventure.book_map(
            catalog,
            places,
            here,
            heroes_at,
            None if master else visited,
            hero.id if hero is not None else None,
            scene_tokens=scene_view,
        )
        sk = sketch.of_place(here, catalog, places)
    else:
        sk = sketch.of_place(here, None, places) if here is not None and (here.state or {}).get("sketch") else None
    return {
        "book": book,
        "sketch": sketch.for_viewer(sk, master, shown) if sk else None,
        "here": {"id": here.id, "name": here.name, "description": here.description or None} if here else None,
        "around": around,
        "scene_view": scene_view,
        "party": party,
        "areas": areas,
        "mode": scene.mode,
        "exits": exits,
        "places": out_places,
        "links": links,
        "bearings": BEARING_NAMES,
    }
