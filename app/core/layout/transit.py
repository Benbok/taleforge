"""Переход между участками комплекса (спецификация 2026-10-12, §5, §7, §8).

``begin`` в транзакции команды проверяет героев и проход, подводит первого героя к проходу (вне боя) и запрашивает
подготовку участка назначения, не меняя места героев. ``finish`` в отдельной транзакции после подготовки заново
проверяет место героев, их клетку у прохода, состояние прохода и ревизию blueprint и только тогда переводит героев;
иначе готовый участок остаётся, а перехода нет. На широком свободном крае герой выходит на той же «полосе», где
перешёл. Переход ведёт сервер: клиент не перемещает героя из-за панорамирования карты.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any

from app.core import combat, sketch, steps
from app.core import positions as grid
from app.core.layout import store
from app.core.layout.contracts import Blueprint, End, Passage
from app.db.models import Campaign, Entity
from app.tools.registry import ToolError

QUEUE = "transits"
STATE_NAMES = {"closed": "закрыт", "locked": "заперт"}
MISSING = "отсюда нет такого прохода"


@dataclass(frozen=True)
class Request:
    hero_ids: tuple[str, ...]
    passage_ref: str
    root_id: str
    source_id: str
    dest_id: str
    blueprint_rev: int
    refs: tuple[str, ...]
    lane: int = 0

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "hero_ids": list(self.hero_ids), "refs": list(self.refs)}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Request:
        return cls(tuple(d["hero_ids"]), d["passage_ref"], d["root_id"], d["source_id"], d["dest_id"],
                   int(d["blueprint_rev"]), tuple(d.get("refs") or ()), int(d.get("lane") or 0))  # fmt: skip


def find_passage(world, place_id: str | None, passage_ref: str) -> tuple[Entity, Blueprint, Passage, End, End]:
    """Корень, blueprint, проход, конец со стороны ``place_id`` и противоположный конец."""
    place = world.entities.get(place_id or "")
    root = store.root_of(world.entities, place)
    roots = [root] if root is not None else [
        e for e in world.entities.values() if e.kind == "location" and (e.state or {}).get("blueprint")
    ]  # fmt: skip
    for r in roots:
        bp = store.blueprint_of(r)
        p = bp.passage(passage_ref) if bp is not None else None
        if p is None:
            continue
        ids = store.area_ids(r)
        for i, end in enumerate(p.ends):
            here = ids.get(end.area_ref) if end.area_ref else end.place_id
            if here == place_id:
                return r, bp, p, end, p.ends[1 - i]
    raise ToolError(MISSING)


def _live(root: Entity, p: Passage) -> dict:
    return {"state": p.state, "hidden": p.hidden, **store.passage_live(root, p.passage_ref)}


def check(world, hero_ids: list[str], passage_ref: str) -> tuple[str, Entity, Blueprint, Passage, End, End]:
    places = {world.actor_place(h) for h in hero_ids}
    if len(places) != 1:
        raise ToolError("проходят вместе только герои из одного места")
    here = places.pop()
    root, bp, p, end, other = find_passage(world, here, passage_ref)
    live = _live(root, p)
    if live["hidden"]:
        raise ToolError(MISSING)  # тайный проход отвечает как несуществующий
    if live["state"] != "open":
        raise ToolError(f"«{p.public_name}» {STATE_NAMES.get(live['state'], live['state'])}: сначала откройте")
    return here, root, bp, p, end, other


def endpoint_cells(world, area_id: str, passage_ref: str) -> list[tuple[int, int]] | None:
    """Клетки у прохода в координатах мастера по текущему эскизу; None — эскиз без этого прохода (ручной)."""
    sk = grid._sketch(world, area_id)
    x = next((x for x in (sk or {}).get("exits") or [] if x.get("passage_ref") == passage_ref), None)
    return sketch.exit_cells(sk, x) if x is not None else None


def _approach(ctx, hero_id: str, here: str, end: End, p: Passage, inverse: list) -> int:
    """Подвести героя к проходу вне боя; вернуть индекс клетки прохода, где он стоит."""
    w = ctx.world
    if end.external:
        return 0  # снаружи комплекса: достаточно быть в этом месте
    cells = endpoint_cells(w, here, p.passage_ref)
    if not cells:
        return 0
    me = grid.to_master(w, here, steps.cell_of(w, hero_id))
    if me in cells:
        return cells.index(me)
    if combat.in_combat(ctx) and combat.fights(w.scene, w.characters, w.entities, hero_id):
        raise ToolError(f"в бою к «{p.public_name}» подходят своим ходом: встаньте у прохода")
    goal = {grid.to_rel(w, here, c) for c in cells}
    route = steps.search(w, here, steps.cell_of(w, hero_id), lambda c: c in goal, hero_id)
    if route is None:
        raise ToolError(f"к «{p.public_name}» не подойти: путь закрыт")
    if route:
        inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "state",
                        "before": copy.deepcopy(w.scene.state)})  # fmt: skip
        grid.set_cell(w, hero_id, route[-1])
        ctx.changed.add(hero_id)
    return cells.index(grid.to_master(w, here, route[-1] if route else steps.cell_of(w, hero_id)))


async def request_area(ctx, area: Entity, inverse: list) -> list[str]:
    """Подготовка участка до входа: геометрия и обстановка. Возвращает ref ещё не готовых фаз."""
    from app.core.world_generation import storage
    from app.tools.master.places import request_preparation

    refs = []
    geo = await store.request_geometry(ctx, area)
    if geo:
        refs.append(geo)
    await request_preparation(ctx, area, inverse)
    row = await storage.find(ctx.session, ctx.campaign.id, area.id, "location_initial")
    if row is not None and row.status in ("unprepared", "preparing") and row.requested_at is not None:
        refs.append(row.id)
    return refs


async def begin(ctx, hero_ids: list[str], passage_ref: str, inverse: list) -> Request:
    w = ctx.world
    for h in hero_ids:
        hero = w.actor(h)
        if not hero.alive or hero.hp.current <= 0:
            raise ToolError(f"{hero.name} без сознания и не может идти")
    here, root, bp, p, end, other = check(w, hero_ids, passage_ref)
    lane = _approach(ctx, hero_ids[0], here, end, p, inverse)
    dest_id = store.area_ids(root).get(other.area_ref) if other.area_ref else other.place_id
    dest = w.entities.get(dest_id or "")
    if dest is None:
        raise ToolError(f"за «{p.public_name}» пока ничего нет")
    refs = await request_area(ctx, dest, inverse)
    return Request(tuple(hero_ids), passage_ref, root.id, here, dest.id, bp.revision, tuple(refs), lane)


async def _geometry_ready(ctx, dest: Entity) -> str | None:
    """Почему в участок ещё нельзя войти; None — можно."""
    from app.core.world_generation import storage

    if store.complex_of(dest) is None:
        return None
    row = await storage.find(ctx.session, ctx.campaign.id, dest.id, "location_geometry")
    if row is not None and row.status == "ready":
        return None
    return row.last_error if row is not None and row.status == "blocked" else "участок ещё готовится"


async def finish(ctx, req: Request, inverse: list | None = None) -> dict[str, Any]:
    from app.tools.master.places import move_heroes

    w = ctx.world
    try:
        here, root, bp, p, end, other = check(w, list(req.hero_ids), req.passage_ref)
    except ToolError as e:
        return {"moved": False, "reason": str(e)}
    if here != req.source_id or root.id != req.root_id or bp.revision != req.blueprint_rev:
        return {"moved": False, "reason": "герои уже не у этого прохода"}
    first = req.hero_ids[0]
    before = grid.to_master(w, here, steps.cell_of(w, first))
    cells = endpoint_cells(w, here, p.passage_ref) if not end.external else None
    if cells and before not in cells:
        return {"moved": False, "reason": f"герой отошёл от «{p.public_name}»"}
    dest = w.entities.get(req.dest_id)
    problem = "участка за проходом нет" if dest is None else await _geometry_ready(ctx, dest)
    if problem:
        return {"moved": False, "reason": f"за «{p.public_name}» пока не пройти: {problem}"}
    inverse = list(inverse or [])
    dice: list = []
    heroes = [w.characters[h] for h in req.hero_ids]
    joined = await move_heroes(ctx, heroes, dest, inverse, dice)
    cell = _arrive(ctx, heroes, dest, p, other, req.lane, inverse)
    out = {"moved": True, "area_id": dest.id, "area": dest.name, "passage": p.public_name,
           "from_cell": list(before), "cell": list(cell) if cell else None, **joined}  # fmt: skip
    ev = await ctx.record("traverse_passage", actor_id=first, target_id=dest.id, payload=out, dice=dice or None,
                          inverse=inverse)  # fmt: skip
    return {**out, "event_id": ev.id}


def _arrive(ctx, heroes, dest: Entity, p: Passage, other: End, lane: int, inverse: list) -> tuple[int, int] | None:
    """Герои встают у прохода с той стороны: первый — на ту же полосу широкого края, остальные — рядом."""
    w = ctx.world
    if other.external:
        return None
    cells = endpoint_cells(w, dest.id, p.passage_ref)
    if not cells:
        return None
    target = cells[min(lane, len(cells) - 1)]
    inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(w.scene.state)})
    first_cell = None
    for hero in heroes:
        got = grid.free_cells_near(w, dest.id, grid.to_rel(w, dest.id, target), 1, hero.id)
        if got:
            grid.set_cell(w, hero.id, got[0])
            first_cell = first_cell or grid.to_master(w, dest.id, got[0])
    return first_cell


async def traverse(maker, preparer, dice_factory, campaign_id: str, hero_id: str, passage_ref: str):
    """Переход по действию игрока: подготовка принята → дождаться её вне транзакции → проверить и перейти."""
    from app.tools.runtime import flush_outbox, open_context

    async with maker() as s:
        c = await s.get(Campaign, campaign_id)
        ctx = await open_context(s, c, dice_factory(), turn_id=None, seat_id=None)
        inverse: list = []
        try:
            req = await begin(ctx, [hero_id], passage_ref, inverse)
        except ToolError as e:
            await s.rollback()
            return {"ok": False, "error": str(e)}, None, []
        await ctx.record("request_passage", actor_id=hero_id, target_id=req.dest_id,
                         payload={"passage_ref": passage_ref, "refs": list(req.refs)}, inverse=inverse,
                         hidden=True)  # fmt: skip
        await flush_outbox(s, ctx)
        await s.commit()
    if req.refs and preparer is not None:
        await preparer.settle(maker, campaign_id, list(req.refs))
    async with maker() as s:
        c = await s.get(Campaign, campaign_id)
        ctx = await open_context(s, c, dice_factory(), turn_id=None, seat_id=None)
        out = await finish(ctx, req)
        messages = await flush_outbox(s, ctx)
        await s.commit()
    return {"ok": True, **out}, ctx, messages
