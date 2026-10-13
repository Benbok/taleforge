"""Ограниченная подготовка вперёд (спецификация 2026-10-12, §8): после входа в участок — геометрия его
непосредственных соседей, не больше ``AHEAD``. Только фаза ``location_geometry`` (код, без модели): наполнение,
знание героев и описание не трогаются, и готовая геометрия игроку ничего не открывает (поставка 2). Тайный
проход соседства не даёт. Исполняет восстановитель (``run_due``), ход и переход её не ждут."""

from __future__ import annotations

from app.core.layout import store
from app.db.models import Entity

AHEAD = 2


async def request_ahead(ctx, area: Entity) -> list[str]:
    from app.core.world_generation import storage

    cx = store.complex_of(area)
    root = ctx.world.entities.get(cx["root_id"]) if cx else None
    bp = store.blueprint_of(root)
    if bp is None:
        return []
    ids = store.area_ids(root)
    out: list[str] = []
    for p, end in sorted(bp.ends_of(cx["area_ref"]), key=lambda x: x[0].passage_ref):
        live = {"state": p.state, "hidden": p.hidden, **store.passage_live(root, p.passage_ref)}
        other = bp.other(p, end)
        if live["hidden"] or other.external:
            continue
        row = await storage.find(ctx.session, ctx.campaign.id, ids.get(other.area_ref) or "", "location_geometry")
        if row is None or not storage.activate(row):
            continue  # уже готово, готовится или заблокировано
        out.append(row.id)
        if len(out) >= AHEAD:
            break
    return out
