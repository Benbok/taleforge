"""Инструменты мастера напрямую, без модели: числа, отказы, журнал, идемпотентность."""

import pytest
from sqlalchemy import select

from app.db.models import ActiveEffect, Campaign, Event, Message
from app.tools.master.entities import encounter_budget
from app.tools.registry import execute, tool_specs
from app.tools.runtime import flush_outbox, open_context
from tests.game import QueueDice, import_base, party, run


@pytest.fixture
def game(client, admin, settings):
    import_base(settings)
    c, heads, ch = party(client, admin)
    return settings, c["id"], ch["id"]


def play(settings, cid, dice, fn):
    async def go(s):
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice(dice), turn_id="t_test", seat_id=None)
        out = await fn(ctx)
        await flush_outbox(s, ctx)
        await s.commit()
        return out

    return run(settings, go)


def call(ctx, name, args, key=None):
    return execute(ctx, name, args, key=key)


def test_invalid_ids_and_idempotency(game):
    settings, cid, hero = game

    async def fn(ctx):
        bad = await call(
            ctx, "roll_check", {"character_id": "ch_fake", "stat": "athletics", "difficulty": "dc.easy", "reason": "x"}
        )
        spec = next(t for t in tool_specs(ctx.world) if t["function"]["name"] == "roll_check")
        enum = spec["function"]["parameters"]["properties"]["character_id"]["enum"]
        args = {"character_id": hero, "stat": "athletics", "difficulty": "dc.medium", "reason": "выбить дверь"}
        first = await call(ctx, "roll_check", args, key="t_test:c1")
        second = await call(ctx, "roll_check", args, key="t_test:c1")
        return bad, enum, first, second

    bad, enum, first, second = play(settings, cid, [12, 1], fn)
    assert not bad["ok"] and "ch_fake" in bad["error"]
    assert hero in enum
    assert first["ok"] and second.get("repeated") and second["result"] == first["result"]
    assert first["result"]["total"] == 12 + 2  # Classless STR 15; no lineage or proficiency bonus


def test_long_call_key_fits_column(game):
    # Gemini приклеивает к id вызова подпись мысли на сотни символов, а колонка ключа — varchar(64)
    settings, cid, hero = game
    key = "t_test:call_81e71ab14bfd__thought__" + "CtIFAWkUfRM6X2RoXUgHNoabUNsyGg1A" * 20
    args = {"character_id": hero, "stat": "athletics", "difficulty": "dc.medium", "reason": "выбить дверь"}

    async def fn(ctx):
        return await call(ctx, "roll_check", args, key=key), await call(ctx, "roll_check", args, key=key)

    first, second = play(settings, cid, [12, 1], fn)
    assert first["ok"] and second.get("repeated") and second["result"] == first["result"]

    async def keys(s):
        return (await s.scalars(select(Event.idempotency_key).where(Event.tool == "roll_check"))).all()

    (stored,) = run(settings, keys)
    assert len(stored) <= 64


def test_potion_and_budget(game):
    settings, cid, hero = game

    async def fn(ctx):
        give = await call(
            ctx, "give_item", {"character_id": hero, "item_template_id": "item.potion_of_healing", "reason": "добыча"}
        )
        big = await call(ctx, "spawn_entity", {"creature_template_id": "creature.adult_red_dragon", "name": "Дракон"})
        return give, big

    give, big = play(settings, cid, [], fn)
    assert give["ok"], give
    assert not big["ok"] and "бюджет" in big["error"]


def test_spawned_creature_hit_points_follow_table_difficulty(game):
    """Средние хиты шаблона (гоблин — 7) масштабируются сложностью стола при появлении существа."""
    settings, cid, _ = game

    async def fn(ctx):
        hp = {}
        for mode in ("easy", "normal", "hard", "deadly"):
            ctx.campaign.difficulty = mode
            sp = await call(
                ctx,
                "spawn_entity",
                {"creature_template_id": "creature.goblin", "name": f"Гоблин {mode}", "attitude": "friendly"},
            )
            assert sp["ok"], sp
            st = ctx.world.entities[sp["result"]["spawned"][0]["id"]].state
            hp[mode] = (st["hp"], st["hp_max"], sp["result"]["hp"])
        return hp

    assert play(settings, cid, [], fn) == {
        "easy": (5, 5, 5),
        "normal": (7, 7, 7),
        "hard": (9, 9, 9),
        "deadly": (11, 11, 11),
    }


def test_spawn_uses_existing_table_difficulty_and_rejects_oversized_encounter(game):
    """Бюджет одной и той же встречи зависит от настройки стола; отклонённые враги не появляются."""
    settings, cid, _ = game

    async def fn(ctx):
        budgets = {}
        for mode in ("easy", "normal", "hard", "deadly"):
            ctx.campaign.difficulty = mode
            one = encounter_budget(ctx, [{"xp": 50}])
            two = encounter_budget(ctx, [{"xp": 50}, {"xp": 50}])
            budgets[mode] = {"one": one, "two": two}
        ctx.campaign.difficulty = "normal"
        rejected = await call(
            ctx, "spawn_entity", {"creature_template_id": "creature.skeleton", "name": "Скелет", "count": 2}
        )
        present_after_reject = len(ctx.world.in_scene_entities())
        accepted = await call(
            ctx, "spawn_entity", {"creature_template_id": "creature.skeleton", "name": "Скелет", "count": 1}
        )
        return budgets, rejected, present_after_reject, accepted

    budgets, rejected, present_after_reject, accepted = play(settings, cid, [], fn)
    assert {mode: data["one"]["cap"] for mode, data in budgets.items()} == {
        "easy": 50,
        "normal": 75,
        "hard": 100,
        "deadly": 150,
    }
    assert budgets["easy"]["one"]["ok"] is False
    assert all(budgets[mode]["one"]["ok"] for mode in ("normal", "hard", "deadly"))
    assert all(not data["two"]["ok"] for data in budgets.values())
    assert not rejected["ok"] and "бюджет" in rejected["error"]
    assert present_after_reject == 0
    assert accepted["ok"] and len(accepted["result"]["spawned"]) == 1


def test_time_expires_effects_and_whisper(game):
    settings, cid, hero = game

    async def fn(ctx):
        eff = await call(
            ctx,
            "apply_effect",
            {
                "target_id": hero,
                "effect_template_id": "condition.poisoned",
                "duration_value": 1,
                "duration_unit": "minute",
                "reason": "отравленная игла",
            },
        )
        t = await call(ctx, "advance_time", {"amount": 2, "unit": "minute", "reason": "ждут"})
        w = await call(ctx, "whisper", {"character_id": hero, "text": "Ты слышишь шорох за стеной."})
        return eff, t, w

    eff, t, w = play(settings, cid, [], fn)
    assert eff["ok"] and t["ok"] and w["ok"], (eff, t, w)

    async def check(s):
        left = (await s.scalars(select(ActiveEffect).where(ActiveEffect.target_id == hero))).all()
        msg = (await s.scalars(select(Message).where(Message.kind == "narration"))).all()
        return left, msg

    left, msgs = run(settings, check)
    assert left == []
    msgs = [m for m in msgs if m.visible_to]
    assert len(msgs) == 1 and len(msgs[0].visible_to) == 2 and msgs[0].content.startswith("Ты слышишь")


def test_effect_keeps_source_and_reason_for_master_and_sheet(game):
    settings, cid, hero = game

    async def fn(ctx):
        sp = await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"})
        gob = sp["result"]["spawned"][0]["id"]
        base = {"target_id": hero, "effect_template_id": "condition.frightened"}
        no_reason = await call(ctx, "apply_effect", base)
        no_source = await call(ctx, "apply_effect", {**base, "reason": "провалил спасбросок Мудрости"})
        ok = await call(ctx, "apply_effect", {**base, "reason": "провалил спасбросок Мудрости", "source": gob})
        return no_reason, no_source, ok, ctx.world.scene_table()

    no_reason, no_source, ok, table = play(settings, cid, [], fn)
    assert not no_reason["ok"] and "reason" in no_reason["error"]
    assert not no_source["ok"] and "source" in no_source["error"]
    assert ok["ok"], ok
    assert ok["result"]["source"] == "Гоблин" and ok["result"]["reason"] == "провалил спасбросок Мудрости"
    line = next(x for x in table.splitlines() if x.startswith(hero))
    assert "Испуганный (источник: Гоблин; провалил спасбросок Мудрости)" in line
    # мастер видит суть правила, а не только название: отступать от источника испуганный может
    assert "Испуганный — " in table and "отходить" in table

    async def check(s):
        return (await s.scalars(select(ActiveEffect).where(ActiveEffect.target_id == hero))).one()

    eff = run(settings, check)
    assert (eff.source, eff.reason) == ("Гоблин", "провалил спасбросок Мудрости")


def test_effect_without_source_rule_needs_no_source(game):
    settings, cid, hero = game

    async def fn(ctx):
        args = {"target_id": hero, "effect_template_id": "condition.poisoned", "reason": "выпил из фляги"}
        return await call(ctx, "apply_effect", args)

    r = play(settings, cid, [], fn)
    assert r["ok"], r
    assert "source" not in r["result"]
