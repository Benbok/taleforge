"""Эскиз места (design/interactive-map.md, шаг 1): форма, выходы и крупные предметы в клетках по 5 футов.

Эскиз рисует мастер инструментом ``sketch_place``, пока отряд в месте; без эскиза схема «Вокруг» пустеет, поэтому
таблица сцены напоминает о нём. Комната готового приключения получает эскиз сама — по клеткам пола и стенам с карты
книги. Хранится в ``entities.state.sketch`` места:

    {shape, cols, rows, party: [c, r], walls: [[c, r]],
     exits: [{side, at, kind, state, name, to, beyond, hidden}],
     features: [{name, kind, cells: [[c0, r0, c1, r1]], cover, hidden}]}

Клетка (0, 0) — северо-западный угол, столбцы растут на восток, строки — на юг. ``party`` — где стоит строй отряда:
относительно него клиент раскладывает героев, существ и предметы по зонам дальности, как раньше.
"""

from __future__ import annotations

from typing import Any

from app.db.models import new_id

SHAPES = {
    "room": "помещение",
    "corridor": "коридор",
    "cave": "пещера",
    "street": "улица",
    "open": "открытое место",
}
SIDES = {"n": "север", "e": "восток", "s": "юг", "w": "запад"}
EXIT_KINDS = {
    "door": "дверь",
    "bars": "решётка",
    "window": "окно",
    "arch": "арка",
    "stairs": "лестница",
    "hatch": "люк",
    "gap": "пролом",
    "passage": "проход",
}
EXIT_STATES = {"open": "открыт", "closed": "закрыт", "locked": "заперт"}
FEATURE_KINDS = {
    "furniture": "обстановка",
    "cover": "укрытие",
    "hazard": "опасность",
    "light": "свет",
    "object": "предмет",
    "nature": "природа",
}
MAX_SIDE = 30
MAX_EXITS = 8
MAX_FEATURES = 16
MAX_WALLS = 300


def side_len(sk: dict, side: str) -> int:
    return sk["cols"] if side in ("n", "s") else sk["rows"]


def check(sk: dict, place_ids: set[str]) -> list[str]:
    """Ошибки эскиза для мастера: всё в пределах места, выходы на краю, предметы не налезают на стены и друг на
    друга, строй отряда на свободной клетке."""
    errors: list[str] = []
    cols, rows = sk["cols"], sk["rows"]
    inside = lambda c, r: 0 <= c < cols and 0 <= r < rows  # noqa: E731
    walls = set()
    for c, r in sk.get("walls") or []:
        if not inside(c, r):
            errors.append(f"стена ({c}, {r}) за пределами места {cols}×{rows}")
        walls.add((c, r))
    taken: dict[tuple[int, int], str] = {}
    feature_ids: set[str] = set()
    entity_ids: set[str] = set()
    for f in sk.get("features") or []:
        feature_id = f.get("id")
        entity_id = f.get("entity_id")
        if feature_id is not None:
            if not isinstance(feature_id, str) or not feature_id:
                errors.append("id детали должен быть непустой строкой")
            elif feature_id in feature_ids:
                errors.append(f"дублирующийся id детали: {feature_id}")
            else:
                feature_ids.add(feature_id)
        if entity_id is not None:
            if not isinstance(entity_id, str) or not entity_id:
                errors.append(f"«{f['name']}»: entity_id должен быть непустой строкой")
            elif entity_id in entity_ids:
                errors.append(f"сущность {entity_id} уже привязана к другой детали")
            else:
                entity_ids.add(entity_id)
        for c0, r0, c1, r1 in f["cells"]:
            if c1 < c0 or r1 < r0:
                errors.append(f"«{f['name']}»: клетки [c0, r0, c1, r1] — от северо-западного угла к юго-восточному")
                continue
            if not (inside(c0, r0) and inside(c1, r1)):
                errors.append(f"«{f['name']}» выходит за пределы места {cols}×{rows}")
                continue
            for c in range(c0, c1 + 1):
                for r in range(r0, r1 + 1):
                    if (c, r) in walls:
                        errors.append(f"«{f['name']}» стоит на стене ({c}, {r})")
                    elif (c, r) in taken and taken[(c, r)] != f["name"]:
                        errors.append(f"«{f['name']}» и «{taken[(c, r)]}» в одной клетке ({c}, {r})")
                    taken.setdefault((c, r), f["name"])
    seen: set[tuple[str, int]] = set()
    for x in sk.get("exits") or []:
        n = side_len(sk, x["side"])
        if not 0 <= x["at"] < n:
            errors.append(f"выход «{x['name']}»: at от 0 до {n - 1} на стороне {SIDES[x['side']]}")
        if (x["side"], x["at"]) in seen:
            errors.append(f"два выхода в одной клетке стороны {SIDES[x['side']]} ({x['at']})")
        seen.add((x["side"], x["at"]))
        if x.get("to") and x["to"] not in place_ids:
            errors.append(f"выход «{x['name']}»: нет места {x['to']}; сначала create_location")
    c, r = sk["party"]
    if not inside(c, r):
        errors.append(f"отряд ({c}, {r}) за пределами места {cols}×{rows}")
    elif (c, r) in walls or (c, r) in taken:
        errors.append(f"отряд ({c}, {r}) стоит на стене или предмете")
    return errors


def describe(sk: dict) -> str:
    """Эскиз одной строкой для таблицы сцены: мастер держит в уме то, что видят игроки."""
    parts = [f"эскиз: {SHAPES.get(sk.get('shape'), sk.get('shape'))} {sk['cols']}×{sk['rows']} клеток"]
    parts.append(f"отряд в ({sk['party'][0]}, {sk['party'][1]})")
    exits = [
        f"{x['name']} ({EXIT_KINDS.get(x['kind'], x['kind'])}, {SIDES[x['side']]} {x['at']}, "
        f"{EXIT_STATES.get(x.get('state') or 'open')}"
        + (f", за ним {x['beyond']}" if x.get("beyond") else "")
        + (f", ведёт в {x['to']}" if x.get("to") else "")
        + (", тайный" if x.get("hidden") else "")
        + ")"
        for x in sk.get("exits") or []
    ]
    if exits:
        parts.append("выходы: " + "; ".join(exits))
    unplaced = [x["name"] for x in sk.get("unplaced_exits") or []]
    if unplaced:
        parts.append("выходы без точных координат на карте: " + "; ".join(unplaced))
    feats = [
        f"{f['name']} {f['cells'][0][:2]}" + (" (тайное)" if f.get("hidden") else "") for f in sk.get("features") or []
    ]
    if feats:
        parts.append("предметы: " + "; ".join(feats))
    return ", ".join(parts[:2]) + (". " + ". ".join(parts[2:]) if parts[2:] else "")


def for_viewer(sk: dict, master: bool, visible_places: set[str]) -> dict:
    """Эскиз для карты: игрок не видит тайных выходов и предметов, а ссылку выхода — только на известное место."""
    out = {k: sk[k] for k in ("shape", "cols", "rows", "party", "walls", "book") if k in sk}
    out["exits"] = [
        {**x, "to": x.get("to") if master or x.get("to") in visible_places else None}
        for x in sk.get("exits") or []
        if master or not x.get("hidden")
    ]
    out["features"] = [f for f in sk.get("features") or [] if master or not f.get("hidden")]
    out["unplaced_exits"] = [
        {**x, "to": x.get("to") if master or x.get("to") in visible_places else None}
        for x in sk.get("unplaced_exits") or []
        if master or not x.get("hidden")
    ]
    return out


def with_feature_ids(sk: dict) -> dict:
    """Новые features получают стабильный ID; старые декоративные записи не изменяются при чтении."""
    return {
        **sk,
        "features": [{**f, "id": f.get("id") or new_id("sf")} for f in sk.get("features") or []],
    }


def linked_entity_ids(sk: dict | None) -> set[str]:
    """Связанные сущности отображаются графическим feature вместо дублирующего токена."""
    return {
        f["entity_id"]
        for f in (sk or {}).get("features") or []
        if isinstance(f.get("entity_id"), str) and f["entity_id"]
    }


def physical_geometry(sk: dict | None, entities: dict[str, Any], location_id: str | None) -> dict | None:
    """A removed/carried object must not leave a phantom blocking feature."""
    if not sk or location_id is None:
        return sk
    from app.core.world_objects import is_nested

    features = []
    for feature in sk.get("features") or []:
        ref = feature.get("entity_id")
        if ref:
            entity = entities.get(ref)
            if (
                entity is None
                or entity.kind != "object"
                or entity.location_id != location_id
                or is_nested(entity)
                or (entity.state or {}).get("world_object", {}).get("physical") == "destroyed"
            ):
                continue
        features.append(feature)
    return {**sk, "features": features}


def project_for_viewer(
    sk: dict,
    master: bool,
    visible_places: set[str],
    entities: dict[str, Any],
    location_id: str,
) -> dict:
    """Единая проверка физического состояния, видимости и связи с реестром на стороне сервера."""
    from app.core.inspect import entity_type
    from app.core.world_objects import is_nested

    out = for_viewer(sk, master, visible_places)
    features = []
    for feature in out["features"]:
        f = dict(feature)
        eid = f.get("entity_id")
        if eid:
            entity = entities.get(eid)
            if (
                entity is None
                or entity.kind != "object"
                or entity.location_id != location_id
                or is_nested(entity)
            ):
                continue
            st = entity.state or {}
            if st.get("world_object", {}).get("physical") == "destroyed":
                continue
            if not master and (st.get("hidden") or st.get("secret")):
                continue
            f["name"] = entity.name
            f["entity_type"] = entity_type(entity)
            f["visual_key"] = st.get("visual_key") if isinstance(st.get("visual_key"), str) else None
        features.append(f)
    out["features"] = features
    out["edit_rev"] = int(sk.get("edit_rev") or 0)
    return out


# --- комната готового приключения: эскиз по карте книги ---


def from_book(mark: dict, grid: dict, neighbours: list[tuple[str, str | None, str]]) -> dict | None:
    """Геометрия комнаты из книги: двери только на подтверждённых клетках.

    neighbours: (публичное имя, entity_id если создана, book room id).
    Отсутствие координат НЕ делает проход несуществующим: он остаётся
    текстовым выходом, не подменяемым выдуманной дверью на эскизе.
    """
    floor = set()
    for c0, r0, c1, r1 in mark.get("cells") or []:
        floor |= {(c, r) for c in range(c0, c1 + 1) for r in range(r0, r1 + 1)}
    if not floor:
        return None
    blocked = {tuple(x) for x in mark.get("blocked") or []}
    box = (min(c for c, _ in floor), min(r for _, r in floor), max(c for c, _ in floor), max(r for _, r in floor))
    c0, r0, c1, r1 = box
    walls = [
        [c - c0, r - r0]
        for r in range(r0, r1 + 1)
        for c in range(c0, c1 + 1)
        if (c, r) not in floor or (c, r) in blocked
    ][:MAX_WALLS]
    from app.core.modules import room_anchor

    anchor = room_anchor(mark)
    if anchor is None:
        return None
    pc, pr = anchor
    marked = {x["to"]: x for x in mark.get("passages") or []}
    exits, unplaced = [], []
    for name, to, rid in neighbours:
        portal = marked.get(rid)
        if portal is None:
            unplaced.append({"name": name, "to": to, "room_ref": rid})
            continue
        c, r = portal["cell"]
        side = portal["side"]
        at = c - c0 if side in ("n", "s") else r - r0
        exits.append(
            {
                "side": side,
                "at": at,
                "kind": portal.get("kind") or "passage",
                "state": "open",
                "name": name,
                "to": to,
                "room_ref": rid,
            }
        )
    return {
        "shape": "room",
        "cols": c1 - c0 + 1,
        "rows": r1 - r0 + 1,
        "party": [pc - c0, pr - r0],
        "walls": walls,
        "exits": exits,
        "unplaced_exits": unplaced,
        "features": [],
        "book": True,
    }


def book_sketch(room: Any, catalog: Any, entities: dict) -> dict | None:
    """Эскиз комнаты модуля, если у неё есть клетки на карте книги и мастер не нарисовал свой."""
    from app.core import adventure

    r = adventure.room_of(room)
    if r is None:
        return None
    adv = adventure.adventure_of(catalog)
    rec = catalog.find(r["of"], "location_template")
    if adv is None or rec is None:
        return None
    mp = next((m for m in adv.data.get("maps") or [] if m.get("location_ref") == rec.id and m.get("grid")), None)
    if mp is None:
        return None
    from app.core.topology import location_exits

    marks = {str(m.get("number")): m for m in mp.get("marks") or []}
    mark = marks.get(str(r.get("number")))
    if mark is None:
        return None
    neighbours = [
        (exit.label or "Неизведанная комната", exit.target_id, exit.room_ref)
        for exit in location_exits(room, catalog, entities)
        if exit.room_ref is not None
    ]
    return from_book(mark, mp["grid"], neighbours)


def of_place(e: Any, catalog: Any, entities: dict) -> dict | None:
    """Эскиз места: нарисованный мастером или, для комнаты книги, построенный по карте."""
    if e is None:
        return None
    sk = (e.state or {}).get("sketch")
    if isinstance(sk, dict) and sk.get("cols"):
        return sk
    try:
        return book_sketch(e, catalog, entities)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
