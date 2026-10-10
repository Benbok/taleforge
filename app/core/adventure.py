"""Кампания по готовому приключению (пункт 13, этап 2): мастер ведёт отряд по комнатам книги.

Модуль — пакет ``module-<slug>`` поверх SRD (app/core/modules.py). Его каркас копируется в ``campaign_secrets.plot``
при создании кампании, места каркаса ссылаются на записи ``location_template`` с комнатами. Место модуля
попадает в реестр мира, как любой набросок каркаса (``develop``), а его комнаты — лениво: инструмент ``enter_room``
заводит комнату, когда отряд в неё входит, и вместе с ней соседние комнаты, чтобы выходы были видны на схеме.

Комната в реестре — место (``kind="location"``) внутри места модуля с ``state.room = {of, id, number}``: ``of`` —
id записи места в пакете, ``id`` — id комнаты в книге. Мастер видит текущую комнату целиком (текст вслух,
проверки со сложностью книги, существа, сокровища, тайное), игрок — только то, что мастер рассказал, а непосещённую
соседнюю комнату — под номером, без названия из книги.
"""

from __future__ import annotations

import copy
from typing import Any

from app.content.catalog import CatalogView, Entry
from app.core.modules import cell_center, place_tokens
from app.core.positions import Pos
from app.core.rolls import ABILITY_RU, SKILL_RU
from app.db.models import Entity

BOOK = "book:"  # сложность проверки из книги: book:<id комнаты в реестре>:<номер проверки с 1>


def room_of(e: Entity | None) -> dict | None:
    """Пометка комнаты модуля у места реестра, если это комната."""
    if e is None or e.kind != "location":
        return None
    r = (e.state or {}).get("room")
    return r if isinstance(r, dict) and r.get("of") and r.get("id") else None


def rooms(rec: Entry | None) -> list[dict]:
    return [r for r in (rec.data.get("rooms") if rec else None) or [] if isinstance(r, dict) and r.get("id")]


def module_place(e: Entity | None, catalog: CatalogView, entities: dict[str, Entity]) -> tuple[Entity, Entry] | None:
    """Место модуля для места реестра: само место, если у его записи есть комнаты, или место, где лежит комната."""
    if e is None or e.kind != "location":
        return None
    if room_of(e) is not None:
        e = entities.get(e.location_id or "")
        if e is None:
            return None
    rec = catalog.find(e.template_id, "location_template") if e.template_id else None
    return (e, rec) if rooms(rec) else None


def find_room(rec: Entry, ref: str) -> dict | None:
    """Комната по id из книги или по номеру на карте."""
    ref = str(ref).strip()
    for r in rooms(rec):
        if r["id"] == ref or str(r.get("number") or "") == ref:
            return r
    low = ref.lower()
    return next((r for r in rooms(rec) if str(r.get("name") or "").lower() == low), None)


def room_title(room: dict) -> str:
    n = room.get("number")
    return f"комната {n} «{room.get('name')}»" if n else f"«{room.get('name')}»"


def room_entity(entities: dict[str, Entity], place: Entity, rid: str) -> Entity | None:
    return next(
        (e for e in entities.values() if e.location_id == place.id and (room_of(e) or {}).get("id") == rid),
        None,
    )


def new_room(campaign_id: str, place: Entity, rec: Entry, room: dict) -> Entity:
    """Комната в реестре. Карточка для игроков — текст вслух из книги: там то, что герои видят с порога."""
    return Entity(
        campaign_id=campaign_id,
        kind="location",
        name=str(room.get("name") or room["id"]),
        description=str(room.get("read_aloud") or "")[:2000],
        state={"room": {"of": rec.id, "id": room["id"], "number": room.get("number")}},
        location_id=place.id,
    )


def public_name(e: Entity, visited: bool) -> str:
    """Имя места для игрока: непосещённая комната книги — под номером, её название из книги может выдать тайну."""
    r = room_of(e)
    if r is None or visited:
        return e.name
    return f"Комната {r['number']}" if r.get("number") else "Неизведанная комната"


def _check_line(i: int, c: dict, room_id: str) -> str:
    what = SKILL_RU.get(c.get("skill") or "") or ABILITY_RU.get(c.get("ability") or "") or "проверка"
    kind = "спасбросок" if c.get("save") else "проверка"
    return f"  {i}. {kind} {what}, СЛ {c.get('dc')} (difficulty {BOOK}{room_id}:{i}): {c.get('text')}"


def room_text(rec: Entry, room: dict, entity: Entity | None, catalog: CatalogView, entities: dict[str, Entity]) -> str:
    """Комната для мастера целиком, по книге."""
    eid = entity.id if entity is not None else "?"
    lines = [f"Комната {room.get('number') or '—'} «{room.get('name')}» ({eid}) в месте «{rec.name}»."]
    if room.get("read_aloud"):
        lines.append(f"Текст вслух из книги (перескажи живо, по сути книги): {room['read_aloud']}")
    if room.get("description"):
        lines.append(f"Что здесь по книге: {room['description']}")
    checks = [c for c in room.get("checks") or [] if isinstance(c, dict)]
    if checks:
        lines.append("Проверки книги — сложность только эта, через roll_check с difficulty из скобок:")
        lines += [_check_line(i, c, eid) for i, c in enumerate(checks, 1)]
    enc = [x for x in room.get("encounters") or [] if isinstance(x, dict)]
    if enc:
        lines.append("Существа комнаты (выведи spawn_entity, когда они проявятся; уже выведенных не дублируй):")
        for x in enc:
            cr = catalog.find(str(x.get("creature_ref")), "creature_template")
            name = cr.name if cr else x.get("creature_ref")
            note = f" — {x['note']}" if x.get("note") else ""
            lines.append(f"  {x.get('count')} × {name} ({x.get('creature_ref')}){note}")
    loot = [x for x in room.get("treasure") or [] if isinstance(x, dict)]
    if loot:
        lines.append("Сокровища (найденное отдавай через keep_found_item или give_item):")
        lines += [f"  {x.get('text')}" + (f" ({x['item_ref']})" if x.get("item_ref") else "") for x in loot]
    if room.get("secrets"):
        lines.append("Тайное (игрокам — только когда найдут): " + "; ".join(map(str, room["secrets"])))
    exits = []
    place_id = entity.location_id if entity is not None else None
    for rid in room.get("exits") or []:
        other = find_room(rec, rid)
        if other is None:
            continue
        there = room_entity(entities, entities[place_id], rid) if place_id in entities else None
        exits.append(room_title(other) + (f" ({there.id})" if there is not None else ""))
    if exits:
        lines.append("Выходы: " + "; ".join(exits) + ". Переход — enter_room с номером комнаты.")
    return "\n".join(lines)


def place_text(rec: Entry) -> str:
    """Место модуля для мастера: общие особенности и список комнат, чтобы он знал планировку."""
    lines = [f"Место готового приключения «{rec.name}»: {rec.data.get('description') or ''}".strip()]
    if rec.data.get("features"):
        lines.append("Особенности: " + "; ".join(map(str, rec.data["features"])))
    lines.append("Комнаты: " + "; ".join(room_title(r) for r in rooms(rec)))
    return "\n".join(lines)


def master_block(world: Any) -> str:
    """Блок «По книге» для мастера: для каждого места, где стоят герои, — комната целиком или место модуля."""
    if not world.campaign or not is_module(world.campaign):
        return ""
    parts = [
        "Это готовое приключение: веди по книге. Описания, проверки со сложностями, существа и сокровища бери из "
        "блока ниже; импровизируй там, куда книга не дотягивается (разговоры, неожиданные решения игроков). "
        "Переход отряда в другую комнату места — enter_room."
    ]
    seen: set[str] = set()
    for pid in world.scene_places():
        e = world.entities.get(pid or "")
        found = module_place(e, world.catalog, world.entities)
        if found is None:
            continue
        place, rec = found
        if place.id not in seen:
            seen.add(place.id)
            parts.append(place_text(rec))
        r = room_of(e)
        room = find_room(rec, r["id"]) if r else None
        if room is not None:
            parts.append(room_text(rec, room, e, world.catalog, world.entities))
        elif r is None:
            parts.append("Отряд у места, но ни в одной комнате: при входе вызови enter_room с номером комнаты.")
    return "\n\n".join(parts) if len(parts) > 1 else ""


def book_dc(ref: str, entities: dict[str, Entity], catalog: CatalogView) -> int | None:
    """Сложность проверки книги по ссылке ``book:<комната>:<номер>``; None — ссылка не на книгу."""
    if not ref.startswith(BOOK):
        return None
    try:
        eid, idx = ref[len(BOOK) :].rsplit(":", 1)
        i = int(idx)
    except ValueError:
        return None
    e = entities.get(eid)
    r = room_of(e)
    rec = catalog.find(r["of"], "location_template") if r else None
    room = find_room(rec, r["id"]) if rec else None
    checks = [c for c in (room or {}).get("checks") or [] if isinstance(c, dict)]
    if not 1 <= i <= len(checks) or not isinstance(checks[i - 1].get("dc"), int):
        return None
    return checks[i - 1]["dc"]


def book_refs(world: Any) -> list[str]:
    """Ссылки на проверки книги в комнатах, где стоят герои: их можно передать в roll_check как difficulty."""
    out = []
    for pid in world.scene_places():
        e = world.entities.get(pid or "")
        r = room_of(e)
        rec = world.catalog.find(r["of"], "location_template") if r else None
        room = find_room(rec, r["id"]) if rec else None
        n = len([c for c in (room or {}).get("checks") or [] if isinstance(c, dict)])
        out += [f"{BOOK}{e.id}:{i}" for i in range(1, n + 1)]
    return out


# --- кампания из модуля ---


def is_module(campaign: Any) -> bool:
    return bool(((campaign.settings or {}) if campaign is not None else {}).get("module"))


def adventure_of(catalog: CatalogView) -> Entry | None:
    found = catalog.by_kind("adventure")
    return found[0] if found else None


def hooks(adv: Entry) -> list[dict]:
    return [h for h in adv.data.get("hooks") or [] if isinstance(h, dict) and h.get("id")]


def start_plan(adv: Entry, hook_id: str | None) -> tuple[dict, dict | None]:
    """Каркас кампании из записи приключения и выбранная зацепка (по умолчанию первая из книги)."""
    plan = copy.deepcopy(adv.data.get("plot") or {})
    hs = hooks(adv)
    hook = next((h for h in hs if h["id"] == hook_id), None) if hook_id else (hs[0] if hs else None)
    if hook is not None:
        plan["module_hook"] = {"id": hook["id"], "title": hook.get("title"), "text": hook.get("text")}
    return plan, hook


def hook_line(plan: dict | None) -> str:
    """Как герои вступают в историю: зацепка книги для вступления."""
    h = (plan or {}).get("module_hook")
    if not isinstance(h, dict) or not h.get("text"):
        return ""
    return f"Как герои вступают в историю (зацепка из книги «{h.get('title')}»): {h['text']}"


# --- карта книги в игре (этап 3) ---


def _token_spots(
    grid: dict | None, mark: dict, tokens: list[tuple[str, float, float]]
) -> dict[str, tuple[float, float]]:
    """Где стоят значки героев на картинке, в долях. С клетками — на свободных клетках комнаты ближе к своим
    позициям сцены; без них — рядом с номером комнаты."""
    if grid and mark.get("cells"):
        cells = place_tokens(grid, mark, tokens)
        if cells:
            return {tid: cell_center(grid, c, r) for tid, (c, r) in cells.items()}
    return {tid: (round(mark["x"] + 0.03 * (i % 4 - 1.5), 4), round(mark["y"] + 0.04, 4)) for i, (tid, _, _) in
            enumerate(tokens)}  # fmt: skip


def book_map(
    catalog: CatalogView,
    places: dict[str, Entity],
    here: Entity | None,
    heroes: list[tuple[Any, str | None, dict]],
    shown: set[str] | None,
    mine: str | None,
    entities: list[Entity] | None = None,
) -> dict | None:
    """Карта места модуля, где стоит отряд: картинка из книги, номера комнат и значки героев.

    ``heroes`` — (персонаж, id места, позиция сцены); ``shown`` — id мест, которые зритель видел (None — мастер,
    он видит все комнаты). Непосещённые комнаты игроку не отмечаются: туман войны — следующий шаг."""
    found = module_place(here, catalog, places)
    adv = adventure_of(catalog)
    if found is None or adv is None:
        return None
    place, rec = found
    mp = next((m for m in adv.data.get("maps") or [] if m.get("location_ref") == rec.id and m.get("marks")), None)
    if mp is None:
        return None
    grid = mp.get("grid")
    rooms_here = {e.id: e for e in places.values() if e.location_id == place.id and room_of(e) is not None}
    by_number = {str(room_of(e).get("number")): e for e in rooms_here.values() if room_of(e).get("number")}
    here_room = room_of(here) if here is not None else None
    here_number = str(here_room.get("number")) if here_room and here_room.get("number") else None
    marks = []
    for m in mp["marks"]:
        num = str(m.get("number"))
        e = by_number.get(num)
        seen = shown is None or (e is not None and e.id in shown)
        if not seen:
            continue
        status = "here" if num == here_number else "visited" if e is not None and e.id in (shown or set()) else "known"
        out = {"number": num, "x": m["x"], "y": m["y"], "status": status, "name": e.name if e is not None else None}
        if m.get("cells"):
            out["cells"] = m["cells"]
        marks.append(out)
    numbers = {m["number"] for m in marks}
    tokens = []
    token_positions: dict[str, tuple[float, float]] = {}
    groups: dict[str, list] = {}
    for ch, pid, pos in heroes:
        e = rooms_here.get(pid or "")
        num = str((room_of(e) or {}).get("number")) if e is not None else None
        if num in numbers:
            groups.setdefault(num, []).append((ch, pos))
    for num, members in groups.items():
        mark = next(m for m in mp["marks"] if str(m.get("number")) == num)
        spots = _token_spots(
            grid,
            mark,
            [(ch.id, *Pos(p.get("zone"), p.get("bearing")).xy(None)) for ch, p in members],
        )
        for ch, pos in members:
            token_positions[ch.id] = Pos(pos.get("zone"), pos.get("bearing")).xy(None)
            x, y = spots[ch.id]
            tokens.append(
                {
                    "id": ch.id,
                    "name": ch.name,
                    "mine": ch.id == mine,
                    "room": num,
                    "x": x,
                    "y": y,
                    "down": (ch.resources or {}).get("hp") == 0,
                }
            )
    # Существа и лежащие в мире предметы находятся в конкретных комнатах.
    # Игрок видит только сущности в своей комнате; мастер — во всех показанных.
    for e in entities or []:
        room = rooms_here.get(e.location_id or "")
        if room is None or e.kind == "location":
            continue
        st = e.state or {}
        if st.get("hidden") or st.get("secret") or st.get("area"):
            continue
        if shown is not None and room.id != (here.id if here is not None else None):
            continue
        num = str((room_of(room) or {}).get("number"))
        mark = next((m for m in mp["marks"] if str(m.get("number")) == num), None)
        if num not in numbers or mark is None:
            continue
        from app.core.inspect import entity_type
        token_positions[e.id] = Pos(e.zone, st.get("bearing")).xy(None)
        x, y = mark["x"], mark["y"]
        tokens.append(
            {
                "id": e.id,
                "name": e.name,
                "mine": False,
                "room": num,
                "x": x,
                "y": y,
                "down": bool(st.get("dead")),
                "type": entity_type(e),
            }
        )
    # Располагаем всех персонажей, существ и предметы комнаты вместе,
    # иначе каждый новый объект занимал бы одну и ту же клетку.
    for num in {t["room"] for t in tokens}:
        mark = next(m for m in mp["marks"] if str(m.get("number")) == num)
        room_tokens = [t for t in tokens if t["room"] == num]
        spots = _token_spots(grid, mark, [(t["id"], *token_positions[t["id"]]) for t in room_tokens])
        for token in room_tokens:
            token["x"], token["y"] = spots[token["id"]]
    return {
        "module_id": adv.data.get("module_id"),
        "map_id": mp["id"],
        "name": rec.name,
        "grid": grid,
        "here": here_number,
        "rooms": marks,
        "tokens": tokens,
    }
