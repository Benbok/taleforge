"""Переход между участками комплекса (спецификация 2026-10-12, §5, §7, §8).

``begin`` в транзакции команды проверяет героев и проход, подводит первого героя к проходу (вне боя) и запрашивает
подготовку участка назначения, не меняя места героев. ``finish`` в отдельной транзакции после подготовки заново
проверяет место героев, их клетку у прохода, состояние прохода и ревизию blueprint и только тогда переводит героев;
иначе готовый участок остаётся, а перехода нет. На широком свободном крае герой выходит на той же «полосе», где
перешёл. Переход ведёт сервер: клиент не перемещает героя из-за панорамирования карты.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import asdict, dataclass
from typing import Any

from app.core import combat, sketch, steps
from app.core import positions as grid
from app.core.layout import store
from app.core.layout.contracts import Blueprint, End, Passage
from app.core.world_tx import WorldConflict
from app.db.models import Campaign, Entity, MasterTurn, Scene
from app.rules.dnd5e import modifiers as mod
from app.tools.registry import ToolError

log = logging.getLogger(__name__)

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
    by_player: bool = False

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "hero_ids": list(self.hero_ids), "refs": list(self.refs)}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Request:
        return cls(tuple(d["hero_ids"]), d["passage_ref"], d["root_id"], d["source_id"], d["dest_id"],
                   int(d["blueprint_rev"]), tuple(d.get("refs") or ()), int(d.get("lane") or 0),
                   bool(d.get("by_player")))  # fmt: skip


def find_passage(
    world,
    place_id: str | None,
    passage_ref: str,
    *,
    known_passages: frozenset[tuple[str, str]] | None = None,
) -> tuple[Entity, Blueprint, Passage, End, End]:
    """Корень, blueprint, проход, конец со стороны ``place_id`` и противоположный конец."""
    roots = [e for e in world.entities.values() if e.kind == "location" and (e.state or {}).get("blueprint")]
    found = []
    for root in roots:
        bp = store.blueprint_of(root)
        p = bp.passage(passage_ref) if bp is not None else None
        hidden_for_hero = known_passages is None or (root.id, passage_ref) not in known_passages
        if p is None or (p.hidden and hidden_for_hero) or (_live(root, p)["hidden"] and hidden_for_hero):
            continue
        ids = store.area_ids(root)
        for i, end in enumerate(p.ends):
            here = ids.get(end.area_ref) if end.area_ref else end.place_id
            if here == place_id:
                found.append((root, bp, p, end, p.ends[1 - i]))
    if len(found) > 1:
        raise ToolError("отсюда ведут несколько проходов с этой ссылкой: попроси мастера уточнить проход")
    if found:
        return found[0]
    raise ToolError(MISSING)


def _live(root: Entity, p: Passage) -> dict:
    return {"state": p.state, "hidden": p.hidden, **store.passage_live(root, p.passage_ref)}


def check(
    world,
    hero_ids: list[str],
    passage_ref: str,
    *,
    known_passages: frozenset[tuple[str, str]] | None = None,
) -> tuple[str, Entity, Blueprint, Passage, End, End]:
    places = {world.actor_place(h) for h in hero_ids}
    if len(places) != 1:
        raise ToolError("проходят вместе только герои из одного места")
    here = places.pop()
    root, bp, p, end, other = find_passage(world, here, passage_ref, known_passages=known_passages)
    live = _live(root, p)
    if live["hidden"] and (known_passages is None or (root.id, passage_ref) not in known_passages):
        raise ToolError(MISSING)  # тайный проход отвечает как несуществующий
    if live["state"] != "open":
        raise ToolError(f"«{p.public_name}» {STATE_NAMES.get(live['state'], live['state'])}: сначала откройте")
    return here, root, bp, p, end, other


def check_heroes(ctx, hero_ids, by_player: bool) -> None:
    """Те же запреты, что у шага героя: сознание, недееспособность и (для игрока) очередь хода в бою."""
    w = ctx.world
    for h in hero_ids:
        hero = w.actor(h)
        if not hero.alive or hero.hp.current <= 0:
            raise ToolError(f"{hero.name} без сознания и не может идти")
        blocked = mod.can_act(hero.modifiers)
        if blocked:
            raise ToolError(f"{hero.name} не может двигаться: {blocked}")
        if by_player and combat.in_combat(ctx) and combat.fights(w.scene, w.characters, w.entities, h):
            if combat.current_id(ctx) != h:
                raise ToolError("в бою ходят по очереди: дождись своего хода")


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


async def begin(
    ctx,
    hero_ids: list[str],
    passage_ref: str,
    inverse: list,
    *,
    by_player: bool = False,
    known_passages: frozenset[tuple[str, str]] | None = None,
) -> Request:
    w = ctx.world
    check_heroes(ctx, hero_ids, by_player)
    if known_passages is None:
        from app.core.map_memory import known_passages as read_known_passages

        known_passages = await read_known_passages(ctx.session, hero_ids[0], w.actor_place(hero_ids[0]))
    here, root, bp, p, end, other = check(w, hero_ids, passage_ref, known_passages=known_passages)
    lane = _approach(ctx, hero_ids[0], here, end, p, inverse)
    dest_id = store.area_ids(root).get(other.area_ref) if other.area_ref else other.place_id
    dest = w.entities.get(dest_id or "")
    if dest is None:
        raise ToolError(f"за «{p.public_name}» пока ничего нет")
    refs = await request_area(ctx, dest, inverse)
    return Request(tuple(hero_ids), passage_ref, root.id, here, dest.id, bp.revision, tuple(refs), lane, by_player)


async def _geometry_ready(ctx, dest: Entity) -> str | None:
    """Почему в участок ещё нельзя войти; None — можно."""
    from app.core.world_generation import storage

    if store.complex_of(dest) is None:
        return None
    row = await storage.find(ctx.session, ctx.campaign.id, dest.id, "location_geometry")
    if row is not None and row.status == "ready":
        return None
    return "участок не удалось подготовить" if row is not None and row.status == "blocked" else "участок ещё готовится"


async def finish(ctx, req: Request, inverse: list | None = None) -> dict[str, Any]:
    from app.tools.master.places import move_heroes

    w = ctx.world
    try:
        check_heroes(ctx, req.hero_ids, req.by_player)
        from app.core.map_memory import known_passages as read_known_passages

        known = await read_known_passages(ctx.session, req.hero_ids[0], w.actor_place(req.hero_ids[0]))
        here, root, bp, p, end, other = check(w, list(req.hero_ids), req.passage_ref, known_passages=known)
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
    from app.core.layout import ahead

    await ahead.request_ahead(ctx, dest)
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


def enqueue(ctx, req: Request, inverse: list) -> None:
    """Переход хода ждёт подготовки: ход завершит его после ``settle``, до описания."""
    sc = ctx.world.scene
    inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(sc.state)})
    queued = [*((sc.state or {}).get(QUEUE) or []), {**req.to_json(), "turn_id": ctx.turn_id}]
    sc.state = {**(sc.state or {}), QUEUE: queued}


async def complete_queued(
    maker,
    preparer,
    dice_factory,
    campaign_id: str,
    bus=None,
    *,
    turn_id: str | None = None,
    panel_only: bool = False,
) -> list[str]:
    """Завершить отложенные переходы кампании: дождаться их подготовок, затем каждый — своей транзакцией.
    Возвращает id событий состоявшихся переходов; несостоявшийся оставляет системную заметку."""
    from app.gateway.events import envelope
    from app.tools.runtime import flush_outbox, open_context, publish_changes

    async with maker() as s:
        sc = await s.get(Scene, campaign_id)
        queued = list(((sc.state or {}) if sc is not None else {}).get(QUEUE) or [])
    queued = [
        q
        for q in queued
        if (turn_id is None or q.get("turn_id") == turn_id) and (not panel_only or q.get("turn_id") is None)
    ]
    if not queued:
        return []
    refs = sorted({r for q in queued for r in q.get("refs") or []})
    if refs and preparer is not None:
        try:
            await preparer.settle(maker, campaign_id, refs)
        except Exception:  # noqa: BLE001 — finish() заново проверит готовность участка
            log.warning("подготовка %s перед переходом не завершилась", refs, exc_info=True)
    done: list[str] = []
    for item in queued:
        try:
            async with maker() as s:
                c = await s.get(Campaign, campaign_id)
                ctx = await open_context(s, c, dice_factory(), turn_id=item.get("turn_id"), seat_id=None)
                sc = ctx.world.scene
                current = (sc.state or {}).get(QUEUE) or []
                if item not in current:
                    continue  # его уже завершил другой исполнитель
                left = [q for q in current if q != item]
                sc.state = {k: v for k, v in {**(sc.state or {}), QUEUE: left}.items() if k != QUEUE or left}
                out = await finish(ctx, Request.from_json(item))
                if out["moved"]:
                    if item.get("turn_id"):
                        turn = await s.get(MasterTurn, item["turn_id"])
                        if turn is not None and turn.generation_checkpoint:
                            cp = turn.generation_checkpoint
                            turn.generation_checkpoint = {
                                **cp,
                                "event_ids": list(dict.fromkeys([*(cp.get("event_ids") or []), out["event_id"]])),
                            }

                else:
                    ctx.outbox.append({"kind": "system", "content": f"Переход не состоялся: {out['reason']}"})
                messages = await flush_outbox(s, ctx)
                await s.commit()
                if out["moved"]:
                    done.append(out["event_id"])  # только подтверждённая фиксация
        except WorldConflict:
            log.info("переход %s: мир изменился, очередь остаётся для повтора", item.get("passage_ref"))
            raise  # ход не переходит к описанию, пока его очередь не обработана
        if bus is not None:
            try:
                await publish_changes(bus, ctx, messages)
                await bus.publish(campaign_id, envelope("map.changed", campaign_id, {}), None)
            except Exception:  # noqa: BLE001 — фиксация перехода не зависит от рассылки
                log.exception("публикация перехода %s не удалась", item.get("passage_ref"))
    return done


async def traverse(
    maker,
    preparer,
    dice_factory,
    campaign_id: str,
    hero_id: str,
    passage_ref: str,
    *,
    expected_source_id: str | None = None,
):
    """Переход по действию игрока: подготовка принята → дождаться её вне транзакции → проверить и перейти.
    Возвращает ответ и список ``(ctx, messages)`` закоммиченных транзакций для публикации изменений."""
    from app.tools.runtime import flush_outbox, open_context

    try:
        async with maker() as s:
            c = await s.get(Campaign, campaign_id)
            ctx1 = await open_context(s, c, dice_factory(), turn_id=None, seat_id=None)
            inverse: list = []
            try:
                if expected_source_id is not None and ctx1.world.actor_place(hero_id) != expected_source_id:
                    return {"ok": False, "error": "переход не удался"}, []
                req = await begin(ctx1, [hero_id], passage_ref, inverse, by_player=True)
            except ToolError as e:
                await s.rollback()
                return {"ok": False, "error": str(e)}, []
            await ctx1.record("request_passage", actor_id=hero_id, target_id=req.dest_id,
                              payload={"passage_ref": passage_ref, "refs": list(req.refs)}, inverse=inverse,
                              hidden=True)  # fmt: skip
            messages1 = await flush_outbox(s, ctx1)
            await s.commit()
    except Exception:
        log.exception("запрос перехода через проход %s не удался", passage_ref)
        return {"ok": False, "error": "переход не удался"}, []
    published = [(ctx1, messages1)]
    try:
        if req.refs and preparer is not None:
            await preparer.settle(maker, campaign_id, list(req.refs))
        async with maker() as s:
            c = await s.get(Campaign, campaign_id)
            ctx = await open_context(s, c, dice_factory(), turn_id=None, seat_id=None)
            out = await finish(ctx, req)
            messages = await flush_outbox(s, ctx)
            await s.commit()
        published.append((ctx, messages))
    except Exception:
        log.exception("переход через проход %s не удался", passage_ref)
        return {"ok": False, "error": "переход не удался"}, published
    return {"ok": True, **out}, published


async def republish(maker, dice_factory, bus, campaign_id: str, hero_ids: list[str]) -> None:
    """Свежее состояние героев и сцены после перехода хода: ход публикует свой прежний контекст, и клиенты
    иначе остались бы с героями в старом участке."""
    from app.gateway.events import envelope
    from app.tools.runtime import open_context, publish_changes

    async with maker() as s:
        c = await s.get(Campaign, campaign_id)
        ctx = await open_context(s, c, dice_factory(), turn_id=None, seat_id=None)
        ctx.changed.update(hero_ids)
    await publish_changes(bus, ctx, [])
    await bus.publish(campaign_id, envelope("map.changed", campaign_id, {}), None)
