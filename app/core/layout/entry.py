"""Вход отряда в комплекс в первой сцене (спецификация 2026-10-12, §6, §8): после готовности структуры отряд
проходит первым открытым подходом во входной участок — тем же путём ``transit.begin``/``finish``, что и переход
мастера: подготовка участка, повторная проверка, перемещение и память вошедших. В игре вход выбирают сами герои."""

from __future__ import annotations

import logging
from typing import Any

from app.core.layout import store, transit
from app.core.layout.contracts import Blueprint
from app.db.models import Campaign, Entity
from app.tools.registry import ToolError

log = logging.getLogger(__name__)


def entry_approach(root: Entity, bp: Blueprint) -> str | None:
    """Открытый подход снаружи (из самого корня) ко входному участку; по ``passage_ref`` для повторяемости."""
    for p in sorted(bp.passages, key=lambda x: x.passage_ref):
        live = {"state": p.state, "hidden": p.hidden, **store.passage_live(root, p.passage_ref)}
        if live["hidden"] or live["state"] != "open":
            continue
        ends = {e.area_ref for e in p.ends if not e.external}
        outside = [e for e in p.ends if e.external and (e.place_id or root.id) == root.id]
        if outside and ends == {bp.entry}:
            return p.passage_ref
    return None


async def enter_complex(maker, preparer, dice_factory, campaign_id: str, root_id: str, bus=None) -> dict[str, Any]:
    from app.core.world import PLAYABLE
    from app.tools.runtime import flush_outbox, open_context, publish_changes

    async with maker() as s:
        c = await s.get(Campaign, campaign_id)
        ctx = await open_context(s, c, dice_factory(), turn_id=None, seat_id=None)
        root = ctx.world.entities.get(root_id)
        bp = store.blueprint_of(root)
        if root is None or bp is None:
            return {"moved": False, "reason": "no_blueprint"}
        heroes = [
            h.id
            for h in ctx.world.characters.values()
            if h.status in PLAYABLE and ctx.world.actor_place(h.id) == root_id
        ]
        if not heroes:
            return {"moved": False, "reason": "no_heroes"}  # уже внутри или ушли: повтор ничего не делает
        ref = entry_approach(root, bp)
        if ref is None:
            return {"moved": False, "reason": "no_approach"}
        inverse: list = []
        try:
            req = await transit.begin(ctx, heroes, ref, inverse)
        except ToolError as e:
            await s.rollback()
            return {"moved": False, "reason": str(e)}
        await ctx.record(
            "request_passage",
            target_id=req.dest_id,
            payload={"passage_ref": ref, "refs": list(req.refs)},
            inverse=inverse,
            hidden=True,
        )
        messages = await flush_outbox(s, ctx)
        await s.commit()
    if bus is not None:
        await publish_changes(bus, ctx, messages)
    if req.refs and preparer is not None:
        await preparer.settle(maker, campaign_id, list(req.refs))
    async with maker() as s:
        c = await s.get(Campaign, campaign_id)
        ctx = await open_context(s, c, dice_factory(), turn_id=None, seat_id=None)
        out = await transit.finish(ctx, req)
        messages = await flush_outbox(s, ctx)
        await s.commit()
    if bus is not None:
        await publish_changes(bus, ctx, messages)
    if not out.get("moved"):
        log.info("отряд не вошёл в комплекс %s: %s", root_id, out.get("reason"))
    return out
