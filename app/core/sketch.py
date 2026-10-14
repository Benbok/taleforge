"""Эскиз места (design/interactive-map.md, шаг 1): форма, выходы и крупные предметы в клетках по 5 футов.

Эскиз рисует мастер инструментом ``sketch_place``, пока отряд в месте; без эскиза схема «Вокруг» пустеет, поэтому
таблица сцены напоминает о нём. Комната готового приключения получает эскиз сама — по клеткам пола и стенам с карты
книги. Хранится в ``entities.state.sketch`` места:

    {shape, cols, rows, party: [c, r], walls: [[c, r]], mask: ["..#"],
     exits: [{side, at, width, cells, kind, state, name, to, beyond, hidden}],
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


def encode_mask(floor: set[tuple[int, int]], cols: int, rows: int) -> list[str]:
    """Маска пола участка неправильной формы: строка на ряд, «.» — пол, «#» — вне участка."""
    return ["".join("." if (c, r) in floor else "#" for c in range(cols)) for r in range(rows)]


def floor_cells(sk: dict | None) -> set[tuple[int, int]] | None:
    """Клетки пола по маске; None — маски нет, пол — весь прямоугольник (старые эскизы и комнаты книги)."""
    mask = (sk or {}).get("mask")
    if not mask:
        return None
    return {(c, r) for r, row in enumerate(mask) for c, ch in enumerate(row) if ch == "."}


def solid_cells(sk: dict | None) -> set[tuple[int, int]]:
    """Непроходимые клетки рамки: стены и всё вне маски пола. Одна мера для шага, пути, прямой видимости и карты."""
    if not sk:
        return set()
    out = {(int(x[0]), int(x[1])) for x in sk.get("walls") or []}
    floor = floor_cells(sk)
    if floor is not None:
        out |= {(c, r) for c in range(sk["cols"]) for r in range(sk["rows"]) if (c, r) not in floor}
    return out


def exit_cells(sk: dict, x: dict) -> list[tuple[int, int]]:
    """Клетки места у выхода, с которых в него входят. Проход комплекса хранит их сам (маска может отодвинуть пол
    от края); у обычного выхода — клетки края на ширине ``width``."""
    if x.get("cells"):
        return [(int(c[0]), int(c[1])) for c in x["cells"]]
    at, side, width = int(x["at"]), x["side"], int(x.get("width") or 1)
    if side == "n":
        return [(at + i, 0) for i in range(width)]
    if side == "s":
        return [(at + i, sk["rows"] - 1) for i in range(width)]
    if side == "w":
        return [(0, at + i) for i in range(width)]
    return [(sk["cols"] - 1, at + i) for i in range(width)]


def check(sk: dict, place_ids: set[str], *, reach: bool = False) -> list[str]:
    """Ошибки эскиза для мастера: всё в пределах места, выходы на краю, предметы не налезают на стены и друг на
    друга, строй отряда на свободной клетке. ``reach`` — ещё и мебель не отрезает выходы и привязанные объекты
    (app/core/reach.py); фоновый эскиз без привязок так не проверяется."""
    errors: list[str] = []
    cols, rows = sk["cols"], sk["rows"]
    inside = lambda c, r: 0 <= c < cols and 0 <= r < rows  # noqa: E731
    mask = sk.get("mask")
    if mask is not None and (len(mask) != rows or any(len(row) != cols or set(row) - {".", "#"} for row in mask)):
        errors.append(f"маска пола: {rows} строк по {cols} символов «.» или «#»")
        mask = None
    void = solid_cells({**sk, "walls": []}) if mask is not None else set()
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
        access = f.get("access_sides")
        if access is not None and (
            not isinstance(access, list) or any(x not in SIDES for x in access) or len(set(access)) != len(access)
        ):
            errors.append(f"«{f['name']}»: access_sides — стороны подхода из n, e, s, w без повторов")
        for c0, r0, c1, r1 in f["cells"]:
            if c1 < c0 or r1 < r0:
                errors.append(f"«{f['name']}»: клетки [c0, r0, c1, r1] — от северо-западного угла к юго-восточному")
                continue
            if not (inside(c0, r0) and inside(c1, r1)):
                errors.append(f"«{f['name']}» выходит за пределы места {cols}×{rows}")
                continue
            for c in range(c0, c1 + 1):
                for r in range(r0, r1 + 1):
                    if (c, r) in void or ((c, r) in walls and f.get("solid") is not True):
                        errors.append(f"«{f['name']}» стоит на стене ({c}, {r})")
                    elif (c, r) in taken and taken[(c, r)] != f["name"]:
                        errors.append(f"«{f['name']}» и «{taken[(c, r)]}» в одной клетке ({c}, {r})")
                    taken.setdefault((c, r), f["name"])
    seen: set[tuple[str, int]] = set()
    for x in sk.get("exits") or []:
        n = side_len(sk, x["side"])
        width = int(x.get("width") or 1)
        if width < 1 or not 0 <= x["at"] <= n - width:
            errors.append(f"выход «{x['name']}»: at от 0 до {n - width} на стороне {SIDES[x['side']]}")
        cells = {(x["side"], x["at"] + i) for i in range(max(width, 1))}
        if cells & seen:
            errors.append(f"два выхода в одной клетке стороны {SIDES[x['side']]} ({min(a for _, a in cells & seen)})")
        seen |= cells
        if x.get("to") and x["to"] not in place_ids:
            errors.append(f"выход «{x['name']}»: нет места {x['to']}; сначала create_location")
    c, r = sk["party"]
    if not inside(c, r):
        errors.append(f"отряд ({c}, {r}) за пределами места {cols}×{rows}")
    elif (c, r) in walls or (c, r) in taken or (c, r) in void:
        errors.append(f"отряд ({c}, {r}) стоит на стене или предмете")
    if reach and not errors:
        from app.core.reach import reach_errors

        errors.extend(reach_errors(sk))
    return errors


def describe(sk: dict) -> str:
    """Эскиз одной строкой для таблицы сцены: мастер держит в уме то, что видят игроки."""
    parts = [f"эскиз: {SHAPES.get(sk.get('shape'), sk.get('shape'))} {sk['cols']}×{sk['rows']} клеток"]
    parts.append(f"отряд в ({sk['party'][0]}, {sk['party'][1]})")
    exits = [
        f"{x['name']} ({EXIT_KINDS.get(x.get('kind', 'door'), x.get('kind', 'door'))}, {SIDES[x['side']]} {x['at']}, "
        f"{EXIT_STATES.get(x.get('state') or 'open')}"
        + (f", за ним {x['beyond']}" if x.get("beyond") else "")
        + (f", ведёт в {x['to']}" if x.get("to") else "")
        + (f", проход {x['passage_ref']}" if x.get("passage_ref") else "")
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
        f"{f['name']} {f['cells'][0][:2]}"
        + (" (тайное)" if f.get("hidden") else "")
        + (
            f" (подход: {', '.join(SIDES[x] for x in f['access_sides'] if x in SIDES)})"
            if f.get("access_sides")
            else ""
        )
        + (" [объект]" if f.get("entity_id") else "")
        for f in sk.get("features") or []
    ]
    if feats:
        parts.append("предметы: " + "; ".join(feats))
    return ", ".join(parts[:2]) + (". " + ". ".join(parts[2:]) if parts[2:] else "")


def for_viewer(sk: dict, master: bool, visible_places: set[str]) -> dict:
    """Эскиз для карты: игрок не видит тайных выходов и предметов, а ссылку выхода — только на известное место."""
    out = {
        k: sk[k]
        for k in (
            "shape",
            "cols",
            "rows",
            "party",
            "walls",
            "book",
            "mask",
            "edges",
            "terrain",
            "material",
            "environment",
        )
        if k in sk
    }
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
    revealed: frozenset[str] = frozenset(),
) -> dict:
    """Единая проверка физического состояния, видимости и связи с реестром на стороне сервера (общая policy,
    app/core/object_policy.py). Тайная деталь объекта, который этот герой явно обнаружил, ему видна; у
    необнаруженной не выдаётся ни геометрия, ни ``entity_id``."""
    from app.core.inspect import entity_type
    from app.core.object_policy import concealed
    from app.core.world_objects import is_nested

    out = for_viewer(sk, master, visible_places)
    if not master:
        shown = {id(f) for f in out["features"]}
        out["features"] = [
            f
            for f in sk.get("features") or []
            if id(f) in shown or (f.get("hidden") and f.get("entity_id") in revealed)
        ]
    features = []
    for feature in out["features"]:
        f = dict(feature)
        eid = f.get("entity_id")
        if eid:
            entity = entities.get(eid)
            if entity is None or entity.kind != "object" or entity.location_id != location_id or is_nested(entity):
                continue
            st = entity.state or {}
            if st.get("world_object", {}).get("physical") == "destroyed":
                continue
            if not master and concealed(entity, entities, revealed):
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


def _live_passages(sk: dict, entities: dict) -> dict:
    """Проход комплекса общий для двух участков: открыт ли он и тайный ли — из ``state.passages`` корня."""
    root = entities.get((sk.get("blueprint") or {}).get("root_id") or "")
    live = ((root.state or {}).get("passages") or {}) if root is not None else {}
    if not live:
        return sk
    exits = []
    for x in sk.get("exits") or []:
        now = live.get(x.get("passage_ref") or "") or {}
        exits.append({**x, **{k: now[k] for k in ("state", "hidden") if k in now}})
    return {**sk, "exits": exits}


def of_place(e: Any, catalog: Any, entities: dict) -> dict | None:
    """Эскиз места: нарисованный мастером или, для комнаты книги, построенный по карте."""
    if e is None:
        return None
    sk = (e.state or {}).get("sketch")
    if isinstance(sk, dict) and sk.get("cols"):
        return _live_passages(sk, entities) if sk.get("blueprint") else sk
    try:
        return book_sketch(e, catalog, entities)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
