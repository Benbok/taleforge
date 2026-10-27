"""Инвентарь и рост героев: подобранные предметы остаются у героя, опыт делится поровну и поднимает уровень."""

import pytest
from sqlalchemy import select

from app.agents.intent import VERBS
from app.db.models import Campaign, Character, Message
from app.tools.registry import execute
from app.tools.runtime import flush_outbox, open_context
from tests.game import FIGHTER, QueueDice, import_base, ok, party, run


def two_heroes(client, admin, settings, **kw):
    import_base(settings)
    c, heads, ch = party(client, admin, players=2, difficulty="deadly", start=False, **kw)
    body = {**FIGHTER, "name": "Ира"}
    ch2 = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=body, headers=heads[1]), 201)
    res = ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch2['id']}/submit", headers=heads[1]))
    assert res["status"] == "approved", res
    ok(client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin))
    return c["id"], ch["id"], ch2["id"], heads


def play(settings, cid, dice, fn):
    async def go(s):
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice(dice), turn_id="t_test", seat_id=None)
        out = await fn(ctx)
        await flush_outbox(s, ctx)
        await s.commit()
        return out

    return run(settings, go)


def call(ctx, name, args):
    return execute(ctx, name, args)


async def kill(ctx, hero, template="creature.goblin", name="Гоблин"):
    sp = await call(ctx, "spawn_entity", {"creature_template_id": template, "name": name, "zone": "melee"})
    assert sp["ok"], sp
    en = sp["result"]["spawned"][0]["id"]
    for _ in range(4):
        r = await call(ctx, "resolve_attack", {"attacker_id": hero, "target_id": en, "attack": "item.longsword"})
        assert r["ok"], r
        if r["result"].get("killed"):
            return en, r
    raise AssertionError("враг не пал")


def sheets(settings, *ids):
    async def go(s):
        return [(await s.get(Character, i)).sheet for i in ids]

    return run(settings, go)


def system_lines(settings):
    async def go(s):
        return [m.content for m in (await s.scalars(select(Message).where(Message.kind == "system"))).all()]

    return run(settings, go)


# --- предметы ---


# --- опыт ---


@pytest.mark.parametrize("verb", ["pick_up", "drop", "give"])
def test_parser_knows_item_verbs(verb):
    assert verb in VERBS
