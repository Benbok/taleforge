"""Фиксы после игровой сессии 2026-10-04: заклинания в таблице сцены, криты с последствием в листе героя,
враги на схеме боя."""

from app.db.models import ActiveEffect
from tests.game import import_base, party
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры хода
from tests.test_spells import wizard_game  # noqa: F401 — фикстура волшебницы
from tests.test_tools import call, play


def test_scene_table_lists_hero_spells(wizard_game):  # noqa: F811
    settings, cid, wiz, _, _ = wizard_game

    async def fn(ctx):
        return ctx.world.scene_table()

    table = play(settings, cid, [], fn)
    line = next(x for x in table.splitlines() if "заклинатель" in x)
    assert "Сл 13" in line and "1-й 2/2" in line
    assert "spell.magic_missile Волшебная стрела (1-й)" in line and "spell.fire_bolt" in line
    assert "spell.burning_hands" not in line  # не подготовлено — сотворить нельзя
    # у воина магии нет: строки «заклинатель» под ним нет
    assert table.count("заклинатель") == 1


def test_crit_fail_must_leave_a_mark_on_hero(game_client, admin_g, llm, dice, settings):  # noqa: F811
    c, (p1,), hero = party(game_client, admin_g)
    dice += [1]
    check = {"character_id": hero["id"], "stat": "sleight_of_hand", "difficulty": "dc.hard", "reason": "штаны"}
    effect = {"target_id": hero["id"], "effect_template_id": "condition.prone", "duration_value": 1,
              "duration_unit": "round"}  # fmt: skip
    llm.replies += [
        {"tool_calls": [("roll_check", check)]},
        DONE,  # модель забыла о последствии — сервер переспрашивает
        {"tool_calls": [("apply_effect", effect)]},
        DONE,
        {"text": "Стражник оборачивается, и вор растягивается на мостовой."},
    ]
    act(game_client, p1, c["id"], "Стаскиваю штаны со стражника")
    tool_msg = next(m for m in llm.requests[1]["messages"] if m["role"] == "tool")
    assert "critical_note" in tool_msg["content"] and "листе" in tool_msg["content"]
    assert "Критический провал без последствия" in llm.requests[2]["messages"][-1]["content"]
    effects = rows(settings, ActiveEffect, ActiveEffect.target_id == hero["id"])
    assert [e.effect_template_id for e in effects] == ["condition.prone"]


def test_crit_success_note_and_no_nudge(client, admin, settings):
    import_base(settings)
    c, _, ch = party(client, admin)
    args = {"character_id": ch["id"], "stat": "athletics", "difficulty": "dc.nearly_impossible", "reason": "x"}

    async def fn(ctx):
        from app.agents.master import _unsettled_fails

        r = await call(ctx, "roll_check", args)
        return r, _unsettled_fails(ctx, [{"tool": "roll_check", "args": args, "result": r}])

    r, fails = play(settings, c["id"], [20], fn)
    assert r["result"]["critical"] == "success" and "близко к задуманному" in r["result"]["critical_note"]
    assert fails == []


def test_combat_start_puts_foes_on_one_side(client, admin, settings):
    import_base(settings)
    c, _, ch = party(client, admin)

    async def fn(ctx):
        ids = []
        for name in ("Бабуин", "Бабуин-вожак"):
            a = await call(ctx, "spawn_entity", {"creature_template_id": "creature.baboon", "name": name})
            assert a["ok"], a
            ids.append(a["result"]["spawned"][0]["id"])
        await call(ctx, "reposition", {"actor_id": ids[0], "bearing": "e"})
        r = await call(ctx, "set_scene_mode", {"mode": "combat"})
        return r, [(ctx.world.entities[i].state or {}).get("bearing") for i in ids]

    r, bearings = play(settings, c["id"], [], fn)
    assert r["ok"], r
    assert bearings == ["e", "e"] and "placed" in r["result"]


def test_cast_window_routes_area_targets_and_leaves_free_target_to_master(wizard_game):  # noqa: F811
    from app.agents import intent as intents
    from app.agents.master import _routable_cast

    settings, cid, wiz, _, _ = wizard_game

    async def fn(ctx):
        a = await call(ctx, "spawn_entity", {"creature_template_id": "creature.baboon", "name": "Бабуин"})
        foe = a["result"]["spawned"][0]["id"]
        ch = ctx.world.characters[wiz]
        area = {"verb": "cast", "spell_id": "spell.fog_cloud", "target_ids": [foe, "en_nope"]}
        free = {"verb": "cast", "spell_id": "spell.light", "free_target": "факел на стене"}
        out = []
        for one in (area, free):
            parsed = intents.check({"kind": "action", "actions": [one], "confidence": 1.0}, ctx.world, ch)
            out.append((parsed, _routable_cast(ctx, {**parsed.intent, "character_id": wiz})))
        return foe, out

    foe, [(area, routed), (free, none)] = play(settings, cid, [], fn)
    assert area.intent["actions"][0]["target_ids"] == [foe]  # чужой id убран
    assert routed["target_ids"] == [foe] and "area_chosen" not in routed
    assert none is None and "факел на стене" in intents.describe(free.intent)
