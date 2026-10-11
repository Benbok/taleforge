"""Места и позиции: перемещение по схеме, области, локации, эскизы, переходы и комнаты модуля."""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from app.core import adventure, audio, combat, economy, sketch
from app.core import positions as grid
from app.core.positions import Pos, active_areas, areas_at, distance, hero_positions, inside, pos_of
from app.core.world import PLAYABLE
from app.core.world_objects import is_nested
from app.db.models import Character, Entity
from app.tools import grapples as gp
from app.tools.master.base import (
    BEARING_HINT,
    CELL_HINT,
    COVER_HINT,
    ELEVATION_HINT,
    PLACE_HINT,
    Bearing,
    Cell,
    Cover,
    Elevation,
    Zone,
    _character,
)
from app.tools.master.checks import _area_hits, enter_areas, roll_initiative
from app.tools.registry import ToolContext, ToolError, tool


class RepositionArgs(BaseModel):
    actor_id: str = Field(description="герой или существо")
    zone: Literal["center", "melee", "near", "far"] | None = Field(
        None, description="где от центра отряда: center — в строю отряда, melee — вплотную, near — близко, far — далеко"
    )
    bearing: Bearing | None = Field(None, description="в какой стороне; n — север (вверх схемы)")
    cell: Cell | None = Field(None, description=CELL_HINT + ". В бою все стоят на клетках: двигай клеткой")
    elevation: Elevation | None = Field(None, description=ELEVATION_HINT)
    cover: Cover | None = Field(None, description=COVER_HINT)


@tool(
    "reposition",
    "Перемещает героя или существо внутри сцены: клетка (точно, в бою — так), или зона от центра отряда и сторона; "
    "высота, укрытие. В бою движение дальше скорости — рывок (тратит действие), дальше двух скоростей — нельзя. "
    "Занятую клетку, стену и предмет эскиза сервер не даст.",
    RepositionArgs,
    ids={"actor_id": "combatants"},
    closes=False,
)
async def reposition(ctx: ToolContext, a: RepositionArgs) -> dict:
    await gp.refresh(ctx)
    w = ctx.world
    act = w.actor(a.actor_id)
    before = pos_of(w, act.id)
    was = {x.id for x in areas_at(w, act.id)}
    after = Pos(before.zone, before.bearing, before.elevation, before.cover, before.cell)
    if a.cell is not None:
        place = w.actor_place(act.id)
        rel = grid.to_rel(w, place, a.cell)
        problem = grid.cell_problem(w, place, rel, act.id)
        if problem:
            raise ToolError(problem)
        after.cell, after.zone, after.bearing = rel, grid.zone_of_cell(rel), grid.bearing_of_cell(rel)
    else:
        if a.zone is not None or a.bearing is not None:
            after.cell = None  # зона и сторона заменяют точную клетку
        if a.zone is not None:
            after.zone = None if a.zone == "center" else a.zone
            if a.zone == "center":
                after.bearing = None
        if a.bearing is not None:
            after.bearing = a.bearing
    if a.elevation is not None:
        after.elevation = a.elevation
    if a.cover is not None:
        after.cover = a.cover
    if act.kind == "creature" and after.zone is None:
        raise ToolError("существо не встаёт в строй отряда: укажите melee, near или far")
    previous_scene_state = copy.deepcopy(w.scene.state)
    moved = 0
    if (after.cell, after.zone, after.bearing, after.elevation) != (
        before.cell,
        before.zone,
        before.bearing,
        before.elevation,
    ):
        moved = distance(before, after)
    out: dict = {"who": act.name, "position": after.public(), "moved_ft": moved}
    if combat.in_combat(ctx) and ctx.world.in_fight(act.id) and moved:
        if act.speed <= 0:
            raise ToolError(f"{act.name}: скорость 0, добровольное перемещение невозможно")
        if act.kind == "character":
            if economy.charge_movement(ctx, act.id, moved):
                out["note"] = "рывок: общая дистанция за ход превысила скорость, действие потрачено"
        else:
            if moved > 2 * act.speed:
                raise ToolError(
                    f"{act.name} проходит за ход не больше {2 * act.speed} футов с рывком, а тут {moved}: "
                    "переместите ближе, остальное — следующим ходом"
                )
            if moved > act.speed:
                out["note"] = f"рывок: {moved} футов больше скорости {act.speed}, действие потрачено на рывок"
    if act.kind == "character":
        sc = w.scene
        inverse = [{"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": previous_scene_state}]
        positions = hero_positions(sc)
        positions[act.id] = after.public()
        sc.state = {**(sc.state or {}), "positions": positions}
    else:
        en = w.entities[act.id]
        inverse = [
            {"table": "entities", "id": en.id, "field": "state", "before": copy.deepcopy(en.state)},
            {"table": "entities", "id": en.id, "field": "zone", "before": en.zone},
        ]
        en.zone = after.zone or en.zone
        st = {**(en.state or {}), "elevation": after.elevation, "cover": after.cover}
        if after.bearing:
            st["bearing"] = after.bearing
        if after.cell is not None:
            st["cell"] = list(after.cell)
        else:
            st.pop("cell", None)
        en.state = st
    w.invalidate(act.id)
    await ctx.record("reposition", actor_id=act.id, target_id=act.id, payload=out, inverse=inverse)
    hit = await enter_areas(ctx, act.id, was)
    if hit:
        out["areas"] = hit
    await gp.refresh(ctx)
    return out


class AreaArgs(BaseModel):
    name: str = Field(max_length=80, description="что это: «Облако трупного газа», «Горящее масло», «Туман»")
    zone: Zone = "near"
    bearing: Bearing | None = Field(None, description="где центр области; n — север (вверх)")
    radius_ft: Literal[5, 10, 15, 20, 30] = Field(10, description="радиус области в футах")
    hazard_template_id: str | None = Field(None, description="опасность по шаблону: срабатывает на тех, кто внутри")
    effect_template_id: str | None = Field(None, description="эффект или состояние на тех, кто внутри")
    duration_rounds: int | None = Field(
        None, ge=1, le=600, description="сколько раундов держится; пусто — пока не уберут"
    )
    location_id: str | None = Field(None, description=PLACE_HINT)


@tool(
    "place_area",
    "Отмечает на схеме область: облако, огонь, туман, лужу масла. Опасность и эффект из шаблонов срабатывают на "
    "всех внутри сразу и на тех, кто войдёт потом.",
    AreaArgs,
    ids={
        "hazard_template_id": "templates:hazard_template",
        "effect_template_id": "templates:effect_template",
        "location_id": "places",
    },
    closes=False,
)
async def place_area(ctx: ToolContext, a: AreaArgs) -> dict:
    w = ctx.world
    if w.scene.location_id is None:
        raise ToolError("у сцены нет места; сначала create_location с make_current")
    place = w.place_arg(a.location_id, "область")
    if a.hazard_template_id:
        rec = w.catalog.get(a.hazard_template_id, "hazard_template")
        if rec.data.get("params_schema"):
            raise ToolError(f"опасности {rec.name} нужны параметры: примените её apply_hazard к каждой цели")
    if a.effect_template_id:
        w.catalog.get(a.effect_template_id, "effect_template")
    area: dict = {"radius_ft": a.radius_ft}
    for k in ("hazard_template_id", "effect_template_id"):
        if getattr(a, k):
            area[k] = getattr(a, k)
    if a.duration_rounds:
        area["expires_at"] = w.scene.game_time + a.duration_rounds * 6
    en = Entity(
        campaign_id=ctx.campaign.id,
        kind="object",
        name=a.name,
        state={"area": area, "landmark": True, **({"bearing": a.bearing} if a.bearing else {})},
        location_id=place,
        zone=a.zone,
    )
    ctx.session.add(en)
    await ctx.session.flush()
    w.entities[en.id] = en
    await ctx.record(
        "place_area",
        target_id=en.id,
        payload={"name": a.name, "zone": a.zone, "radius_ft": a.radius_ft},
        inverse=[{"table": "entities", "op": "delete", "id": en.id}],
    )
    ids = [c.id for c in w.characters.values() if c.status in PLAYABLE] + [
        e.id for e in w.in_scene_entities(place) if e.kind == "creature" and not (e.state or {}).get("dead")
    ]
    caught = [i for i in ids if inside(w, en, i)]
    hits = [await _area_hits(ctx, en, i) for i in caught]
    return {"area_id": en.id, "name": a.name, "inside": [w.actor(i).name for i in caught], "hits": hits}


class RemoveAreaArgs(BaseModel):
    area_id: str


@tool("remove_area", "Убирает область со схемы: облако рассеялось, огонь погас.", RemoveAreaArgs, closes=False)
async def remove_area(ctx: ToolContext, a: RemoveAreaArgs) -> dict:
    en = ctx.world.entities.get(a.area_id)
    if en is None or not (en.state or {}).get("area"):
        ids = ", ".join(f"{e.id} {e.name}" for e in active_areas(ctx.world)) or "нет"
        raise ToolError(f"нет области {a.area_id}; области сцены: {ids}")
    inverse = [{"table": "entities", "id": en.id, "field": "location_id", "before": en.location_id}]
    en.location_id = None
    await ctx.record("remove_area", target_id=en.id, payload={"name": en.name}, inverse=inverse)
    return {"removed": en.name}


class CreateLocationArgs(BaseModel):
    name: str = Field(max_length=128)
    description: str = Field(
        "", max_length=2000, description="как место выглядит для героев: это текст карточки для игроков, без тайн"
    )
    template_id: str | None = Field(None, description="шаблон локации пакета, если есть подходящий")
    make_current: bool = Field(False, description="сразу сделать текущей локацией сцены")
    parent_id: str | None = Field(None, description="внутри какого места находится: район туши, дом на улице, комната")
    link_to: list[str] = Field(
        default_factory=list, max_length=6, description="соседние места, куда отсюда можно пройти (появятся на карте)"
    )
    via: str | None = Field(None, max_length=40, description="чем связаны с соседями: лестница, переулок, тоннель")
    bearing: Bearing | None = Field(None, description="в какой стороне от текущего места; n — север (вверх)")
    secret: bool = Field(False, description="тайное место: на карте только после того, как герои его нашли")


def _link(a: Entity, b_id: str, label: str | None = None, bearing: str | None = None) -> bool:
    """Путь между местами хранится у места ``a`` в ``state.links``. Повтор не добавляет второй путь."""
    st = dict(a.state or {})
    links = list(st.get("links") or [])
    if any(x.get("to") == b_id for x in links):
        return False
    links.append({"to": b_id, **({"label": label} if label else {}), **({"bearing": bearing} if bearing else {})})
    st["links"] = links
    a.state = st
    return True


def _linked(ctx: ToolContext | None, a: Entity, b: Entity) -> bool:
    """Места уже связаны на карте: путь в любую сторону или одно внутри другого."""
    return (
        a.location_id == b.id
        or b.location_id == a.id
        or any(x.get("to") == b.id for x in (a.state or {}).get("links") or [])
        or any(x.get("to") == a.id for x in (b.state or {}).get("links") or [])
    )


def _connect(ctx: ToolContext, a: Entity, b: Entity, inverse: list) -> None:
    """В свободном мире пройденный маршрут отмечается; в книге переходы заданы её планом."""
    if adventure.room_of(a) and adventure.room_of(b) and a.location_id == b.location_id:
        return  # Переход персонажей не создаёт новую дверь между комнатами модуля.
    if a.id != b.id and not _linked(ctx, a, b):
        inverse.append({"table": "entities", "id": a.id, "field": "state", "before": copy.deepcopy(a.state)})
        _link(a, b.id)


def _visit(ctx: ToolContext, loc: Entity, heroes: list[Character], inverse: list) -> None:
    st = dict(loc.state or {})
    seen = list(st.get("visited_by") or [])
    new = [h.id for h in heroes if h.id not in seen]
    if not new:
        return
    inverse.append({"table": "entities", "id": loc.id, "field": "state", "before": copy.deepcopy(loc.state)})
    st["visited_by"] = seen + new
    loc.state = st


def _reset_positions(ctx: ToolContext, inverse: list) -> None:
    """В новом месте герои снова стоят в строю отряда."""
    sc = ctx.world.scene
    if hero_positions(sc):
        inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(sc.state)})
        sc.state = {k: v for k, v in (sc.state or {}).items() if k != "positions"}


def _clear_positions(ctx: ToolContext, hero_ids: set[str], inverse: list) -> None:
    """Убирает позиции конкретных героев из scene.state.positions (они в новом месте — старые координаты неверны)."""
    sc = ctx.world.scene
    positions = hero_positions(sc)
    to_clear = {hid for hid in hero_ids if hid in positions}
    if not to_clear:
        return
    inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(sc.state)})
    new_positions = {k: v for k, v in positions.items() if k not in to_clear}
    sc.state = (
        {**(sc.state or {}), "positions": new_positions}
        if new_positions
        else {k: v for k, v in (sc.state or {}).items() if k != "positions"}
    )


def relocate_scene(ctx: ToolContext, loc: Entity, inverse: list) -> None:
    """Сцена переходит в новое место вместе с героями, которые стояли в старом: место отмечается посещённым,
    а старое и новое связываются на карте, если ещё не связаны."""
    old_id = ctx.world.scene.location_id
    old = ctx.world.entities.get(old_id or "")
    party = [c for c in ctx.world.characters.values() if c.status in PLAYABLE]
    going = [c for c in party if (c.location_id or old_id) == old_id]
    if old is not None and old.id != loc.id:
        _visit(ctx, old, going, inverse)
        _connect(ctx, old, loc, inverse)
    for c in going:
        if c.location_id is not None and c.location_id != loc.id:
            inverse.append({"table": "characters", "id": c.id, "field": "location_id", "before": c.location_id})
            c.location_id = loc.id
    inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "location_id", "before": old_id})
    _reset_positions(ctx, inverse)
    ctx.world.scene.location_id = loc.id
    _visit(ctx, loc, going, inverse)
    ctx.signals.add("map.changed")


@tool(
    "create_location",
    "Регистрирует локацию в реестре мира (по шаблону пакета, если он есть). Место сразу попадает на карту героев: "
    "укажи, внутри чего оно и с какими местами соседствует.",
    CreateLocationArgs,
    ids={"parent_id": "locations", "link_to": "locations"},
    closes=False,
)
async def create_location(ctx: ToolContext, a: CreateLocationArgs) -> dict:
    state: dict = {}
    if a.template_id:
        rec = ctx.world.catalog.get(a.template_id, "location_template")
        if rec.data.get("dc") is not None:
            state["dc"] = rec.data["dc"]
    if a.bearing:
        state["bearing"] = a.bearing
    if a.secret:
        state["secret"] = True
    en = Entity(
        campaign_id=ctx.campaign.id,
        kind="location",
        name=a.name,
        template_id=a.template_id,
        description=a.description,
        state=state,
        location_id=a.parent_id,
    )
    ctx.session.add(en)
    await ctx.session.flush()
    ctx.world.entities[en.id] = en
    inverse = [{"table": "entities", "op": "delete", "id": en.id}]
    for other in dict.fromkeys(a.link_to):
        if other != en.id:
            _link(en, other, a.via)
    if a.make_current:
        relocate_scene(ctx, en, inverse)
    await ctx.record(
        "create_location",
        target_id=en.id,
        payload={"name": a.name, "current": a.make_current, "parent": a.parent_id, "links": a.link_to},
        inverse=inverse,
    )
    return {"location_id": en.id, "name": a.name, "current": a.make_current}


class LinkArgs(BaseModel):
    from_id: str
    to_id: str
    via: str | None = Field(None, max_length=40, description="чем связаны: лестница, переулок, тоннель, люк")
    bearing: Bearing | None = Field(None, description="в какой стороне от from_id; n — север (вверх)")


@tool(
    "link_locations",
    "Отмечает на карте путь между двумя местами реестра: герои нашли проход, лестницу, тоннель.",
    LinkArgs,
    ids={"from_id": "locations", "to_id": "locations"},
    closes=False,
)
async def link_locations(ctx: ToolContext, a: LinkArgs) -> dict:
    if a.from_id == a.to_id:
        raise ToolError("место не связывают само с собой")
    src, dst = ctx.world.entities[a.from_id], ctx.world.entities[a.to_id]
    before = copy.deepcopy(src.state)
    if not _link(src, dst.id, a.via, a.bearing):
        return {"linked": False, "note": "путь уже отмечен"}
    await ctx.record(
        "link_locations",
        target_id=src.id,
        payload={"from": src.name, "to": dst.name, "via": a.via},
        inverse=[{"table": "entities", "id": src.id, "field": "state", "before": before}],
    )
    return {"linked": True, "from": src.name, "to": dst.name}


class LandmarkArgs(BaseModel):
    name: str = Field(max_length=128, description="что видно: «Фонтан с костяной чашей», «Запертая дверь»")
    description: str = Field("", max_length=1000, description="как это выглядит для героев, без тайн")
    zone: Zone = "near"
    bearing: Bearing | None = Field(None, description=BEARING_HINT)
    cell: Cell | None = Field(None, description=CELL_HINT + "; на стене можно: картина, факел, крюк")
    location_id: str | None = Field(None, description=PLACE_HINT)


@tool(
    "add_landmark",
    "Отмечает на схеме места заметную примету: дверь, статую, лавку, провал. Механики у приметы нет: для существ — "
    "spawn_entity, для отдельного места, куда можно войти, — create_location.",
    LandmarkArgs,
    ids={"location_id": "places"},
    closes=False,
)
async def add_landmark(ctx: ToolContext, a: LandmarkArgs) -> dict:
    if ctx.world.scene.location_id is None:
        raise ToolError("у сцены нет места; сначала create_location с make_current")
    place = ctx.world.place_arg(a.location_id, "примета")
    rel = None
    if a.cell is not None:
        rel = grid.to_rel(ctx.world, place, a.cell)
        problem = grid.floor_problem(ctx.world, place, rel, wall_ok=True)
        if problem:
            raise ToolError(problem)
    en = Entity(
        campaign_id=ctx.campaign.id,
        kind="object",
        name=a.name,
        description=a.description,
        state={"landmark": True, **({"bearing": a.bearing} if a.bearing else {})},
        location_id=place,
        zone=a.zone,
    )
    ctx.session.add(en)
    await ctx.session.flush()
    ctx.world.entities[en.id] = en
    if rel is not None:
        grid.set_cell(ctx.world, en.id, rel)
    await ctx.record(
        "add_landmark",
        target_id=en.id,
        payload={"name": a.name, "zone": a.zone},
        inverse=[{"table": "entities", "op": "delete", "id": en.id}],
    )
    return {"landmark_id": en.id, "name": a.name}


class SketchExit(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="как его видят герои: «Дверь решётки», «Узкое окно»")
    side: Literal["n", "e", "s", "w"] = Field(description="край места: n — северный (верх схемы)")
    at: int = Field(ge=0, description="клетка на этом краю: для n и s — столбец, для e и w — строка, с нуля")
    kind: Literal["door", "bars", "window", "arch", "stairs", "hatch", "gap", "passage"] = "door"
    state: Literal["open", "closed", "locked"] = "open"
    to: str | None = Field(None, description="место реестра, куда ведёт, если оно уже есть")
    beyond: str | None = Field(None, max_length=60, description="что видно или известно за ним: «тёмный коридор»")
    hidden: bool = Field(False, description="тайный выход: игроки не видят, пока не найдут")


class SketchFeature(BaseModel):
    id: str | None = Field(None, min_length=1, max_length=32, description="постоянный id элемента эскиза")
    entity_id: str | None = Field(None, description="опциональная привязка к Entity.kind=object в этом месте")
    name: str = Field(min_length=1, max_length=60, description="«Каменный стол», «Колонна», «Жаровня»")
    kind: Literal["furniture", "cover", "hazard", "light", "object", "nature"] = "object"
    cells: list[list[int]] = Field(
        min_length=1, max_length=4, description="прямоугольники [c0, r0, c1, r1] от северо-западной клетки"
    )
    cover: Literal["none", "half", "three_quarters", "total"] = "none"
    hidden: bool = Field(False, description="игроки не видят, пока не найдут")


class SketchArgs(BaseModel):
    shape: Literal["room", "corridor", "cave", "street", "open"] = "room"
    cols: int = Field(ge=1, le=sketch.MAX_SIDE, description="ширина с запада на восток, клеток по 5 футов")
    rows: int = Field(ge=1, le=sketch.MAX_SIDE, description="длина с севера на юг, клеток по 5 футов")
    party: list[int] = Field(min_length=2, max_length=2, description="клетка [c, r], где сейчас стоит отряд")
    walls: list[list[int]] = Field(
        default_factory=list, max_length=sketch.MAX_WALLS, description="непроходимые клетки [c, r]: колонны, обвал"
    )
    exits: list[SketchExit] = Field(default_factory=list, max_length=sketch.MAX_EXITS)
    features: list[SketchFeature] = Field(default_factory=list, max_length=sketch.MAX_FEATURES)
    location_id: str | None = Field(None, description=PLACE_HINT)
    expected_revision: int | None = Field(
        None, ge=0, description="ревизия текущего эскиза для защиты от устаревших правок"
    )


def sketch_data(a: SketchArgs, places: set[str]) -> tuple[dict, list[str]]:
    """Эскиз из аргументов и ошибки для того, кто его нарисовал (мастер или техническая модель)."""
    for f in a.features:
        if any(len(c) != 4 for c in f.cells):
            return {}, [f"«{f.name}»: каждая клетка предмета — [c0, r0, c1, r1]"]
    if any(len(c) != 2 for c in a.walls):
        return {}, ["стена — клетка [c, r]"]
    # Keep optional exit keys such as "to": None: link_exits relies on the original schema.
    data = a.model_dump(exclude={"location_id", "expected_revision"})
    data["walls"] = [list(x) for x in dict.fromkeys(tuple(c) for c in a.walls)]
    return data, sketch.check(data, places)


def link_exits(place: Entity, data: dict, entities: dict) -> None:
    """Выход в известное место — путь и на карте мест."""
    for x in data["exits"]:
        other = entities.get(x["to"] or "")
        if other is not None and other.id != place.id and not _linked(None, place, other):
            _link(place, other.id, x["name"])


def _validate_feature_bindings(w, place: Entity, data: dict) -> None:
    """Never accept an LLM/entity reference from another room, campaign, inventory or closed container."""
    for feature in data.get("features") or []:
        entity_id = feature.get("entity_id")
        if not entity_id:
            continue
        entity = w.entities.get(entity_id)
        if (
            entity is None
            or entity.campaign_id != place.campaign_id
            or entity.kind != "object"
            or entity.location_id != place.id
            or is_nested(entity)
            or (entity.state or {}).get("world_object", {}).get("physical") == "destroyed"
        ):
            raise ToolError(f"«{feature['name']}»: entity_id {entity_id} не принадлежит открытому объекту этой комнаты")


async def _lock_sketch_place(ctx: ToolContext, place: Entity) -> None:
    """Serialize overlapping edits before checking edit_rev on PostgreSQL."""
    await ctx.session.flush()
    await ctx.session.refresh(place, with_for_update=True)


def _verify_sketch_revision(current: dict, expected: int | None, *, replacing: bool = False) -> int:
    revision = int(current.get("edit_rev") or 0)
    if expected is not None and expected != revision:
        raise ToolError(f"устаревшая ревизия эскиза: ожидалась {expected}, текущая {revision}")
    if replacing and expected is None and sketch.linked_entity_ids(current):
        raise ToolError(f"у эскиза есть связанные объекты: укажи expected_revision={revision}")
    return revision


@tool(
    "sketch_place",
    "Эскиз места для схемы игроков: форма и размер в клетках по 5 футов, где стоит отряд, входы и выходы (дверь, "
    "решётка, окно, лестница) и что за ними, крупные предметы в поле зрения. Клетка (0, 0) — северо-западный угол. "
    "Новый вызов заменяет эскиз целиком. Существ сюда не клади — для них spawn_entity.",
    SketchArgs,
    ids={"location_id": "places"},
    closes=False,
)
async def sketch_place(ctx: ToolContext, a: SketchArgs) -> dict:
    w = ctx.world
    if w.scene.location_id is None:
        raise ToolError("у сцены нет места; сначала create_location с make_current")
    place = w.entities[w.place_arg(a.location_id, "эскиз")]
    await _lock_sketch_place(ctx, place)
    current = (place.state or {}).get("sketch") or {}
    revision = _verify_sketch_revision(current, a.expected_revision, replacing=True)
    data, errors = sketch_data(a, {e.id for e in w.entities.values() if e.kind == "location"})
    if errors:
        raise ToolError("; ".join(errors[:8]))
    _validate_feature_bindings(w, place, data)
    # Existing linked features may only be overwritten by an explicit revision-aware replacement.
    data = sketch.with_feature_ids(data)
    data["edit_rev"] = revision + 1
    before = copy.deepcopy(place.state)
    link_exits(place, data, w.entities)
    data["rev"] = int((place.state or {}).get("layout_rev") or 0)  # нарисован после этого описания: фон не заменит
    place.state = {**(place.state or {}), "sketch": data}
    await ctx.record(
        "sketch_place",
        target_id=place.id,
        payload={"place": place.name, "size": [a.cols, a.rows], "exits": len(a.exits), "features": len(a.features)},
        inverse=[{"table": "entities", "id": place.id, "field": "state", "before": before}],
    )
    return {"place": place.name, "sketch": sketch.describe(data)}


class EditSketchArgs(BaseModel):
    action: Literal[
        "reveal", "hide", "open", "close", "lock", "unlock", "to_exit", "remove", "add_feature", "add_exit"
    ] = Field(
        description="reveal — герои нашли тайное (выход или предмет эскиза); hide — спрятать; open, close, lock, "
        "unlock — состояние выхода (unlock — отперт, но закрыт); to_exit — предмет эскиза оказался выходом "
        "(«камень» — дверь в форме камня), нужен exit; remove — убрать деталь; add_feature, add_exit — новая "
        "деталь, замеченная при осмотре"
    )
    target: str | None = Field(
        None, max_length=60, description="название выхода или предмета эскиза, как в таблице сцены (не для add_*)"
    )
    rename: str | None = Field(None, max_length=60, description="новое имя, если герои увидели, что это на самом деле")
    feature: SketchFeature | None = Field(None, description="для add_feature")
    exit: SketchExit | None = Field(None, description="для add_exit и to_exit: выход на краю места")
    location_id: str | None = Field(None, description=PLACE_HINT)
    expected_revision: int | None = Field(None, ge=0)


def _find(items: list[dict], name: str, what: str) -> int:
    want = name.strip().lower()
    for i, x in enumerate(items):
        if x.get("id") == name or x["name"].strip().lower() == want:
            return i
    have = ", ".join(f"«{x['name']}»" for x in items) or "нет"
    raise ToolError(f"в эскизе нет {what} «{name}»; есть: {have}")


@tool(
    "edit_sketch",
    "Правит одну деталь эскиза места, не перерисовывая его: герои нашли тайную дверь, отперли решётку, заметили "
    "картину на стене, «камень» оказался дверью. Остальной эскиз остаётся как был.",
    EditSketchArgs,
    ids={"location_id": "places"},
    closes=False,
)
async def edit_sketch(ctx: ToolContext, a: EditSketchArgs) -> dict:
    w = ctx.world
    if w.scene.location_id is None:
        raise ToolError("у сцены нет места; сначала create_location с make_current")
    place = w.entities[w.place_arg(a.location_id, "эскиз")]
    await _lock_sketch_place(ctx, place)
    current = sketch.of_place(place, w.catalog, w.entities)
    if current is None:
        raise ToolError(f"у места «{place.name}» ещё нет эскиза: describe_place или sketch_place")
    revision = _verify_sketch_revision(current, a.expected_revision, replacing=bool(sketch.linked_entity_ids(current)))
    data = copy.deepcopy(current)
    exits, feats = list(data.get("exits") or []), list(data.get("features") or [])
    note = ""
    if a.action in ("add_feature", "add_exit"):
        part = a.feature if a.action == "add_feature" else a.exit
        if part is None:
            raise ToolError(f"{a.action}: нужен {'feature' if a.action == 'add_feature' else 'exit'}")
        (feats if a.action == "add_feature" else exits).append(part.model_dump())
        note = part.name
    else:
        if not a.target:
            raise ToolError("укажи target — название детали из эскиза")
        names = [x["name"].strip().lower() for x in exits] + [x.get("id") for x in exits]
        is_exit = a.target.strip().lower() in names
        if a.action in ("open", "close", "lock", "unlock") and not is_exit:
            _find(exits, a.target, "выхода")
        if a.action == "to_exit":
            i = _find(feats, a.target, "предмета")
            if a.exit is None:
                raise ToolError("to_exit: нужен exit — на каком краю и какой это выход")
            feats.pop(i)
            exits.append({**a.exit.model_dump(), **({"name": a.rename} if a.rename else {})})
        elif is_exit:
            i = _find(exits, a.target, "выхода")
            x = dict(exits[i])
            if a.action == "remove":
                exits.pop(i)
            else:
                state = {"open": "open", "close": "closed", "lock": "locked", "unlock": "closed"}.get(a.action)
                if state:
                    x["state"] = state
                if a.action in ("reveal", "hide"):
                    x["hidden"] = a.action == "hide"
                if a.rename:
                    x["name"] = a.rename
                exits[i] = x
        else:
            i = _find(feats + exits, a.target, "выхода или предмета")
            f = dict(feats[i])
            if a.action == "remove":
                feats.pop(i)
            elif a.action in ("reveal", "hide"):
                f["hidden"] = a.action == "hide"
                if a.rename:
                    f["name"] = a.rename
                feats[i] = f
            else:
                raise ToolError(f"«{f['name']}» — предмет эскиза: для него reveal, hide, remove или to_exit")
        note = a.rename or a.target
    data["exits"], data["features"] = exits, feats
    data = sketch.with_feature_ids(data)
    errors = sketch.check(data, {e.id for e in w.entities.values() if e.kind == "location"})
    if errors:
        raise ToolError("; ".join(errors[:8]))
    _validate_feature_bindings(w, place, data)
    data["edit_rev"] = revision + 1
    before = copy.deepcopy(place.state)
    link_exits(place, data, w.entities)
    data["auto"] = False  # правка мастера: фоновая перерисовка по старому описанию её не заменит
    data["rev"] = int((place.state or {}).get("layout_rev") or 0)
    place.state = {**(place.state or {}), "sketch": data}
    await ctx.record(
        "edit_sketch",
        target_id=place.id,
        payload={"place": place.name, "action": a.action, "target": note},
        inverse=[{"table": "entities", "id": place.id, "field": "state", "before": before}],
    )
    return {"place": place.name, "sketch": sketch.describe(data)}


class BindSketchFeatureArgs(BaseModel):
    location_id: str | None = Field(None, description=PLACE_HINT)
    feature_id: str = Field(min_length=1, max_length=32, description="стабильный id из sketch.features")
    entity_id: str | None = Field(None, description="id физического объекта, None — отвязать")
    expected_revision: int = Field(ge=0, description="edit_rev с последнего map.state")


@tool(
    "bind_sketch_feature",
    "Привязывает существующий геометрический элемент к объекту Entity в той же комнате; "
    "не создаёт предметов и не меняет геометрию. Проверяет версию эскиза.",
    BindSketchFeatureArgs,
    ids={"location_id": "places"},
    closes=False,
)
async def bind_sketch_feature(ctx: ToolContext, a: BindSketchFeatureArgs) -> dict:
    w = ctx.world
    place = w.entities[w.place_arg(a.location_id, "эскиз")]
    await _lock_sketch_place(ctx, place)
    current = (place.state or {}).get("sketch")
    if not isinstance(current, dict):
        raise ToolError("у места нет сохранённого эскиза")
    revision = _verify_sketch_revision(current, a.expected_revision)
    data = copy.deepcopy(current)
    features = data.get("features") or []
    feature = next((x for x in features if x.get("id") == a.feature_id), None)
    if feature is None:
        raise ToolError("не найден feature_id; обновите эскиз карты")
    if a.entity_id:
        feature["entity_id"] = a.entity_id
    else:
        feature.pop("entity_id", None)
    errors = sketch.check(data, {e.id for e in w.entities.values() if e.kind == "location"})
    if errors:
        raise ToolError("; ".join(errors[:8]))
    _validate_feature_bindings(w, place, data)
    before = copy.deepcopy(place.state)
    data["edit_rev"] = revision + 1
    data["auto"] = False
    place.state = {**(place.state or {}), "sketch": data}
    result = {"feature_id": a.feature_id, "entity_id": a.entity_id, "revision": data["edit_rev"]}
    await ctx.record(
        "bind_sketch_feature",
        target_id=place.id,
        payload=result,
        inverse=[{"table": "entities", "id": place.id, "field": "state", "before": before}],
    )
    return result


class DescribePlaceArgs(BaseModel):
    layout: str = Field(
        min_length=40,
        max_length=3000,
        description="закрытое описание для схемы (игроки его не видят): форма и размер в футах, откуда вошёл отряд, "
        "каждый вход и выход (дверь, решётка, окно, лестница) — на какой стене, открыт ли, что за ним; крупные "
        "предметы и где стоят; тайное (тайник, скрытая дверь)",
    )
    location_id: str | None = Field(None, description=PLACE_HINT)


@tool(
    "describe_place",
    "Закрытое описание места, куда пришли герои: по нему техническая модель сама построит эскиз для схемы игроков "
    "(форма, выходы, крупные предметы). Описывай одно место — то, где отряд сейчас. Описание видишь только ты, в "
    "таблице сцены; эскиз появится там же, поправить его — sketch_place.",
    DescribePlaceArgs,
    ids={"location_id": "places"},
    closes=False,
)
async def describe_place(ctx: ToolContext, a: DescribePlaceArgs) -> dict:
    w = ctx.world
    if w.scene.location_id is None:
        raise ToolError("у сцены нет места; сначала create_location с make_current")
    place = w.entities[w.place_arg(a.location_id, "описание места")]
    before = copy.deepcopy(place.state)
    st = dict(place.state or {})
    st["layout"] = a.layout.strip()
    st["layout_rev"] = int(st.get("layout_rev") or 0) + 1
    place.state = st
    ctx.signals.add(f"sketch:{place.id}")  # эскиз строится после хода, в фоне (app/agents/surveyor.py)
    await ctx.record(
        "describe_place",
        target_id=place.id,
        payload={"place": place.name},
        inverse=[{"table": "entities", "id": place.id, "field": "state", "before": before}],
        hidden=True,
    )
    return {"place": place.name, "note": "эскиз строится по описанию; появится в таблице сцены"}


class MoveArgs(BaseModel):
    character_ids: list[str] = Field(min_length=1)
    location_id: str


@tool(
    "move",
    "Перемещает героев в локацию реестра. Если уходят все герои — локация становится текущей сценой. Путь сам "
    "отмечается на карте.",
    MoveArgs,
    ids={"character_ids": "characters", "location_id": "locations"},
)
async def move(ctx: ToolContext, a: MoveArgs) -> dict:
    loc = ctx.world.entities.get(a.location_id)
    if loc is None or loc.kind != "location":
        raise ToolError(f"нет локации {a.location_id}; сначала create_location")
    inverse: list = []
    dice: list = []
    joined = await move_heroes(ctx, [_character(ctx, cid) for cid in a.character_ids], loc, inverse, dice)
    await ctx.record(
        "move",
        target_id=loc.id,
        payload={"characters": a.character_ids, "location": loc.name, **joined},
        dice=dice or None,
        inverse=inverse,
    )
    return {"moved": a.character_ids, "location": loc.name, "scene_location": ctx.world.scene.location_id, **joined}


class EnterRoomArgs(BaseModel):
    room: str = Field(min_length=1, max_length=40, description="номер комнаты на карте книги или её id")
    character_ids: list[str] = Field(
        default_factory=list, description="кто входит; пусто — все герои, что стоят там же, где сцена"
    )
    location_id: str | None = Field(
        None, description="место модуля или комната в нём, откуда идут; нужно, только если отряд разделён"
    )


@tool(
    "enter_room",
    "Готовое приключение: герои входят в комнату места по номеру из книги. Комната и соседние с ней появляются в "
    "реестре и на карте; в ответе — комната целиком по книге (текст вслух, проверки, существа, сокровища, тайное).",
    EnterRoomArgs,
    ids={"character_ids": "characters", "location_id": "places"},
)
async def enter_room(ctx: ToolContext, a: EnterRoomArgs) -> dict:
    w = ctx.world
    start = w.place_arg(a.location_id, "отряд входит в комнату")
    found = adventure.module_place(w.entities.get(start or ""), w.catalog, w.entities)
    if found is None:
        raise ToolError("герои не в месте готового приключения: сначала разверни место каркаса через develop")
    place, rec = found
    room = adventure.find_room(rec, a.room)
    if room is None:
        listed = "; ".join(adventure.room_title(r) for r in adventure.rooms(rec))
        raise ToolError(f"в месте «{rec.name}» нет комнаты {a.room}. Комнаты: {listed}")
    inverse: list = []

    async def ensure(r: dict) -> Entity:
        en = adventure.room_entity(w.entities, place, r["id"])
        if en is None:
            en = adventure.new_room(ctx.campaign.id, place, rec, r)
            ctx.session.add(en)
            await ctx.session.flush()
            w.entities[en.id] = en
            inverse.insert(0, {"table": "entities", "op": "delete", "id": en.id})
        return en

    target = await ensure(room)
    from app.core.topology import location_exits

    for passage in location_exits(target, w.catalog, w.entities):
        other = adventure.find_room(rec, passage.room_ref) if passage.room_ref else None
        if other is not None:
            nxt = await ensure(other)
            if not _linked(ctx, target, nxt):
                inverse.append(
                    {"table": "entities", "id": target.id, "field": "state", "before": copy.deepcopy(target.state)}
                )
                _link(target, nxt.id)
    if a.character_ids:
        heroes = [_character(ctx, cid) for cid in a.character_ids]
    else:
        heroes = [c for c in w.characters.values() if c.status in PLAYABLE and w.place_of(c) == start]
    if not heroes:
        raise ToolError("некому входить: назови героев в character_ids")
    dice: list = []
    joined = await move_heroes(ctx, heroes, target, inverse, dice)
    await ctx.record(
        "enter_room",
        target_id=target.id,
        payload={"characters": [h.id for h in heroes], "location": target.name, "room": room.get("number"), **joined},
        dice=dice or None,
        inverse=inverse,
    )
    return {
        "room_id": target.id,
        "moved": [h.id for h in heroes],
        "book": adventure.room_text(rec, room, target, w.catalog, w.entities),
        **joined,
    }


async def move_heroes(ctx: ToolContext, heroes: list[Character], loc: Entity, inverse: list, dice: list) -> dict:
    """Герои переходят в место ``loc``: посещения и пути на карте, вход в бой и выход из него, сцена — за отрядом."""
    scene_loc = ctx.world.scene.location_id
    moved = []
    for ch in heroes:
        was = ctx.world.entities.get(ch.location_id or scene_loc or "")
        if was is not None and was.id != loc.id:
            _visit(ctx, was, [ch], inverse)
            _connect(ctx, was, loc, inverse)
        inverse.append({"table": "characters", "id": ch.id, "field": "location_id", "before": ch.location_id})
        ch.location_id = loc.id
        moved.append(ch)
    _visit(ctx, loc, moved, inverse)
    party = [c for c in ctx.world.characters.values() if c.status in PLAYABLE]
    if not all(c.location_id == loc.id for c in party):
        _clear_positions(ctx, {ch.id for ch in moved}, inverse)
    joined = await _move_in_combat(ctx, moved, inverse, dice)
    if all(c.location_id == loc.id for c in party):
        inverse.append(
            {"table": "scenes", "id": ctx.campaign.id, "field": "location_id", "before": ctx.world.scene.location_id}
        )
        if ctx.world.scene.location_id != loc.id:
            _reset_positions(ctx, inverse)
        ctx.world.scene.location_id = loc.id
    ctx.signals.add("map.changed")
    return joined


async def _move_in_combat(ctx: ToolContext, moved: list, inverse: list, dice: list) -> dict:
    """Идёт бой: герой, ушедший из места боя, выходит из очереди; пришедший в место боя бросает инициативу и
    встаёт в очередь (5e: опоздавший вступает в бой)."""
    if not combat.in_combat(ctx):
        return {}
    sc = ctx.world.scene
    inverse += [
        {"table": "scenes", "id": ctx.campaign.id, "field": f, "before": copy.deepcopy(getattr(sc, f))}
        for f in ("mode", "round", "turn_order", "state")
    ]
    fronts = {combat._at(ctx, x["id"]) for x in sc.turn_order if x["id"] not in ctx.world.characters}
    have = {x["id"] for x in sc.turn_order}
    out: dict = {}
    left = combat.drop(ctx, {ch.id for ch in moved if ch.id in have and ch.location_id not in fronts})
    if left:
        out["left_combat"] = [ctx.world.characters[i].name for i in left]
    came = [ch.id for ch in moved if ch.id not in have and ch.location_id in fronts]
    if came:
        entries, rolls_ = roll_initiative(ctx, came)
        combat.insert(ctx, entries)
        dice += rolls_
        out["joined_combat"] = [f"{ctx.world.characters[e['id']].name} ({e['initiative']})" for e in entries]
    if not sc.turn_order:  # в бою никого не осталось
        sc.mode, sc.round = "free", 0
        combat.end_combat(ctx)
        audio.on_mode(ctx, "free")
    return out
