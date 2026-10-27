# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Пошаговый режим: очередь, ходы существ по профилю, бегство и атака по возможности, раунды, таймаут, кто пишет."""

from app.core import combat
from app.db.models import Campaign, Scene
from app.tools.runtime import open_context
from tests.game import QueueDice, run
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_tools import call, game, play  # noqa: F401 — фикстура game


async def _fight(ctx, hero, template, *, zone="far", first="creature", hp=None, name="Враг"):
    """Существо на сцене и бой с заданной очередью: кто ходит первым."""
    r = await call(ctx, "spawn_entity", {"creature_template_id": template, "name": name, "zone": zone})
    assert r["ok"], r
    eid = r["result"]["spawned"][0]["id"]
    if hp is not None:
        en = ctx.world.entities[eid]
        en.state = {**en.state, "hp": hp}
    r = await call(ctx, "set_scene_mode", {"mode": "combat"})
    assert r["ok"], r
    order = [{"id": eid, "initiative": 20}, {"id": hero, "initiative": 10}]
    ctx.world.scene.turn_order = order if first == "creature" else order[::-1]
    combat.start_combat(ctx)
    return eid


def attacks(ctx, attacker):
    return [e for e in ctx.events if e.tool == "resolve_attack" and e.actor_id == attacker]


def _setup(settings, cid, hero, template, **kw):
    async def go(s):
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice([]), turn_id=None, seat_id=None)
        eid = await _fight(ctx, hero, template, **kw)
        if kw.get("first") == "hero":
            combat._begin_hero_turn(ctx, ctx.world.characters[hero])
        await s.commit()
        return eid

    return run(settings, go)


def scene(settings, cid):
    return run(settings, lambda s: s.get(Scene, cid))
