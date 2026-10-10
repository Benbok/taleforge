# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Пошаговый режим: очередь, ходы существ по профилю, бегство и атака по возможности, раунды, таймаут, кто пишет."""

import asyncio

from app.core import combat
from app.db.models import Campaign, Event, MasterTurn, Scene
from app.tools.runtime import open_context
from tests.game import QueueDice, run
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_tools import call, game, play  # noqa: F401 — фикстура game
from tests.test_ws import connect, next_of


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


def test_aggressive_creature_closes_in_then_attacks(game):
    settings, cid, hero = game

    async def fn(ctx):
        gob = await _fight(ctx, hero, "creature.goblin", zone="far")
        notes = await combat.run_until_hero(ctx, "k1")
        # на сетке гоблин проходит 30 футов и ещё стреляет из лука: движение и атака в одном ходу (SRD)
        assert ctx.world.entities[gob].zone == "near" and len(attacks(ctx, gob)) == 1
        assert combat.current_id(ctx) == hero and combat.state(ctx)["deadline"]
        assert any("подходит" in n for n in notes)  # бой на сетке: шесть клеток за ход
        await combat.finish_turn(ctx, notes)
        notes += await combat.run_until_hero(ctx, "k2")
        assert ctx.world.entities[gob].zone == "melee" and len(attacks(ctx, gob)) == 2
        return ctx.world.scene.round, ctx.world.scene.game_time, notes

    rnd, _, notes = play(settings, cid, [], fn)
    assert rnd == 2 and "раунд 2" in notes


def test_multiattack(game):
    settings, cid, hero = game

    async def fn(ctx):
        ch = ctx.world.characters[hero]
        ch.sheet = {**ch.sheet, "level": 5}  # медведь (1 ПО) укладывается в бюджет встречи
        bear = await _fight(ctx, hero, "creature.brown_bear", zone="melee")
        await combat.run_until_hero(ctx, "k")
        return [e.payload.get("attack") for e in attacks(ctx, bear)]

    assert len(play(settings, cid, [], fn)) == 2


def test_cowardly_flees_and_opportunity_attack(game):
    settings, cid, hero = game
    asked = []

    async def yes(ctx, ch, creature):
        asked.append((ch.id, creature.id))
        return True

    async def fn(ctx):
        wolf = await _fight(ctx, hero, "creature.wolf", zone="melee", hp=4)
        notes = await combat.run_until_hero(ctx, "k", yes)
        oa = attacks(ctx, hero)
        assert asked == [(hero, wolf)] and len(oa) == 1
        en = ctx.world.entities[wolf]
        assert en.state.get("fled") or en.state.get("dead")
        return notes, ctx.world.scene.mode

    notes, mode = play(settings, cid, [], fn)
    assert any("вдогонку" in n for n in notes)
    assert mode == "free" and any("бой окончен" in n for n in notes)


def test_round_advance_expires_and_game_time(game):
    settings, cid, hero = game

    async def fn(ctx):
        await _fight(ctx, hero, "creature.goblin", zone="far", first="hero")
        t0, r0 = ctx.world.scene.game_time, ctx.world.scene.round
        assert combat.current_id(ctx) == hero
        notes: list[str] = []
        await combat.finish_turn(ctx, notes)
        notes += await combat.run_until_hero(ctx, "k")
        return ctx.world.scene.game_time - t0, ctx.world.scene.round - r0, combat.current_id(ctx)

    dt, dr, cur = play(settings, cid, [], fn)
    assert (dt, dr, cur) == (combat.ROUND_SECONDS, 1, hero)


def test_fight_ends_when_enemies_down(game):
    settings, cid, hero = game

    async def fn(ctx):
        gob = await _fight(ctx, hero, "creature.goblin", hp=0)
        en = ctx.world.entities[gob]
        en.state = {**en.state, "dead": True}
        notes = await combat.run_until_hero(ctx, "k")
        return notes, ctx.world.scene.mode, ctx.world.scene.state

    notes, mode, st = play(settings, cid, [], fn)
    assert mode == "free" and "бой окончен: врагов не осталось" in notes and "turn" not in st


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


def test_gate_and_turn_pass(game_client, admin_g, llm, settings):
    from tests.game import party

    c, (p1,), hero = party(game_client, admin_g, master={"type": "owner"})
    _setup(settings, c["id"], hero["id"], "creature.goblin", zone="far")
    with connect(game_client, p1, c["id"]) as (ws, snap):
        assert snap["payload"]["turn"]["actor_id"] != hero["id"]
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "бью"}})
        assert "сейчас ход" in next_of(ws, "message.rejected")["payload"]["reason"]
        ws.send_json({"type": "message.send", "payload": {"kind": "ooc", "text": "я подожду"}})
        assert next_of(ws, "message.new")["payload"]["kind"] == "ooc"
        ws.send_json({"type": "turn.pass", "payload": {}})
        assert next_of(ws, "error")["payload"]["code"] == "not_your_turn"
    # мастер закрывает ход существа: очередь переходит к герою
    with connect(game_client, admin_g, c["id"]) as (ws, _):
        ws.send_json({"type": "turn.pass", "payload": {}})
        changed = next_of(ws, "turn.changed")["payload"]["turn"]
    assert changed["actor_id"] == hero["id"] and changed["deadline"]
    with connect(game_client, p1, c["id"]) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "бью"}})
        assert next_of(ws, "message.new")["payload"]["kind"] == "action"
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "и ещё раз"}})
        assert "уже заявлено" in next_of(ws, "message.rejected")["payload"]["reason"]
        ws.send_json({"type": "turn.pass", "payload": {}})
        turn = next_of(ws, "turn.changed")["payload"]["turn"]
    assert turn["actor_id"] == hero["id"] and turn["round"] == 2
    ev = rows(settings, Event, Event.campaign_id == c["id"], Event.tool == "turn_end")
    assert [e.payload["reason"] for e in ev] == ["pass"]


def test_timeout_default_action(game_client, admin_g, llm, settings):
    from tests.game import party

    c, (p1,), hero = party(game_client, admin_g, master={"type": "owner"})
    _setup(settings, c["id"], hero["id"], "creature.goblin", zone="far", first="hero")
    marker = combat.turn_marker(scene(settings, c["id"]))
    master = game_client.app.state.master
    assert game_client.portal.call(master.run_timeout, c["id"], "другой ход") is None
    assert game_client.portal.call(master.run_timeout, c["id"], marker)
    sc = scene(settings, c["id"])
    assert sc.round == 2 and sc.state["actor"] == hero["id"]
    ev = rows(settings, Event, Event.campaign_id == c["id"], Event.tool == "turn_end")
    assert ev[0].payload["action"] == "выжидает"


def test_agent_turn_runs_creatures_and_reaction(game_client, admin_g, llm, settings):
    """Герой бьёт, ход переходит к трусливому волку с 4 хитами: волк бежит, игрок жмёт кнопку реакции."""
    from tests.game import party

    c, (p1,), hero = party(game_client, admin_g)
    _setup(settings, c["id"], hero["id"], "creature.wolf", zone="melee", hp=4, first="hero")
    llm.replies += [DONE, DONE, {"text": "Волк скулит и бросается прочь."}]
    with connect(game_client, p1, c["id"]) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "жду, что сделает волк"}})
        prompt = next_of(ws, "reaction.prompt")["payload"]
        assert prompt["character_id"] == hero["id"] and prompt["options"][0]["id"] == "opportunity_attack"
        ws.send_json(
            {"type": "reaction.choose", "payload": {"prompt_id": prompt["prompt_id"], "option": "opportunity_attack"}}
        )
        assert next_of(ws, "reaction.closed")["payload"]["choice"] == "opportunity_attack"
        for _ in range(40):
            e = ws.receive_json()
            if e["type"] == "message.new" and e["payload"]["kind"] == "narration":
                break
    turns = rows(settings, MasterTurn, MasterTurn.campaign_id == c["id"], MasterTurn.status == "done")
    notes = turns[-1].trace["combat"]
    assert any("вдогонку" in n for n in notes) and any("бой окончен" in n for n in notes)
    assert scene(settings, c["id"]).mode == "free"


def test_reaction_declined(game):
    """Без ответа реакция не тратится: волк просто убегает."""
    settings, cid, hero = game

    async def no(ctx, ch, creature):
        await asyncio.sleep(0)
        return False

    async def fn(ctx):
        await _fight(ctx, hero, "creature.wolf", zone="melee", hp=4)
        notes = await combat.run_until_hero(ctx, "k", no)
        return notes, combat.reaction_available(ctx, hero), attacks(ctx, hero)

    notes, available, oa = play(settings, cid, [], fn)
    assert available and not oa and any("бежит" in n for n in notes)


def test_opening_attack_is_resolved_only_in_initiative_order(game):
    """The declared attack is queued, not dealt as free damage before combat turns."""
    settings, cid, hero = game

    async def fn(ctx):
        enemy = await _fight(ctx, hero, "creature.goblin", zone="melee", first="hero")
        attack = {"attacker_id": hero, "target_id": enemy, "attack": "item.longsword"}
        combat.queue_opening_attack(ctx, attack)
        assert attacks(ctx, hero) == []
        assert combat.state(ctx)["opening_attacks"][hero] == attack
        notes = await combat.run_until_hero(ctx, "opening")
        assert len(attacks(ctx, hero)) == 1
        assert not combat.state(ctx).get("opening_attacks")
        # A dying or fleeing opponent can legitimately close the encounter.
        if combat.in_combat(ctx):
            assert combat.current_id(ctx) == hero
            assert ctx.world.scene.round >= 2
        else:
            assert ctx.world.scene.mode == "free"
        return notes

    notes = play(settings, cid, [], fn)
    assert any("атакует" in n for n in notes)


def test_opening_attack_waits_for_creatures_that_win_initiative(game):
    settings, cid, hero = game

    async def fn(ctx):
        enemy = await _fight(ctx, hero, "creature.goblin", zone="melee", first="creature")
        combat.queue_opening_attack(ctx, {"attacker_id": hero, "target_id": enemy, "attack": "item.longsword"})
        notes = await combat.run_until_hero(ctx, "opening")
        observed = [e.actor_id for e in ctx.events if e.tool == "resolve_attack"]
        assert hero in observed and observed.index(enemy) < observed.index(hero)
        if combat.in_combat(ctx):
            assert combat.current_id(ctx) == hero
        else:
            assert ctx.world.scene.mode == "free"
        return notes

    assert play(settings, cid, [], fn)


def test_opening_attack_out_of_range_is_not_fabricated_as_miss(game):
    settings, cid, hero = game

    async def fn(ctx):
        enemy = await _fight(ctx, hero, "creature.goblin", zone="far", first="hero")
        combat.queue_opening_attack(ctx, {"attacker_id": hero, "target_id": enemy, "attack": "item.longsword"})
        notes = await combat.run_until_hero(ctx, "opening")
        assert not attacks(ctx, hero)
        assert ctx.world.scene.round == 1 and combat.current_id(ctx) == hero
        assert not combat.state(ctx).get("opening_attacks")
        assert combat.state(ctx)["deadline"] is not None
        assert any("не выполнена" in n and "сблизиться" in n for n in notes)
        deadline = combat.state(ctx)["deadline"]
        await combat.run_until_hero(ctx, "repeat-sync")
        assert combat.state(ctx)["deadline"] == deadline
        return notes

    assert play(settings, cid, [], fn)


def test_ending_combat_discards_unresolved_opening_actions(game):
    settings, cid, hero = game

    async def fn(ctx):
        enemy = await _fight(ctx, hero, "creature.goblin", zone="melee", first="creature")
        combat.queue_opening_attack(ctx, {"attacker_id": hero, "target_id": enemy, "attack": "item.longsword"})
        ended = await call(ctx, "set_scene_mode", {"mode": "free"})
        assert ended["ok"], ended
        assert ctx.world.scene.mode == "free"
        assert "opening_attacks" not in combat.state(ctx)

    play(settings, cid, [], fn)


def test_compound_opening_approach_and_attack_runs_in_order(game):
    """The opening declaration moves on the grid before its single legal strike."""
    settings, cid, hero = game

    async def fn(ctx):
        enemy = await _fight(ctx, hero, "creature.goblin", zone="near", first="hero")
        plan = {"attacker_id": hero, "target_id": enemy, "attack": "item.longsword"}
        combat.queue_opening_plan(ctx, plan)
        assert not attacks(ctx, hero)
        notes = await combat.run_until_hero(ctx, "compound-opening")
        events = [e for e in ctx.events if e.tool in ("step", "resolve_attack") and e.actor_id == hero]
        assert [e.tool for e in events] == ["step", "resolve_attack"]
        assert len(attacks(ctx, hero)) == 1
        assert not combat.state(ctx).get("opening_plans")
        assert any("сближается" in n for n in notes)
        return events[0].payload["moved_ft"]

    assert play(settings, cid, [10, 10, 15, 1], fn) > 0


def test_compound_opener_out_of_reach_preserves_turn(game):
    """Do not invent movement or a missed attack if the hero cannot reach."""
    settings, cid, hero = game

    async def fn(ctx):
        enemy = await _fight(ctx, hero, "creature.goblin", zone="far", first="hero")
        combat.queue_opening_plan(ctx, {"attacker_id": hero, "target_id": enemy, "attack": "item.longsword"})
        notes = await combat.run_until_hero(ctx, "unreachable")
        assert combat.current_id(ctx) == hero
        assert combat.state(ctx)["deadline"] is not None
        assert not combat.state(ctx).get("opening_plans")
        assert not attacks(ctx, hero)
        assert not [e for e in ctx.events if e.tool == "step" and e.actor_id == hero]
        assert any("сближение" in n or "подтверждения" in n for n in notes)
        return notes

    assert play(settings, cid, [10, 10], fn)


def test_compound_attack_refusal_keeps_remaining_turn(game):
    """Moving is real even when the weapon is not usable; the action is not spent."""
    from app.tools.action_plan import execute_approach_attack

    settings, cid, hero = game

    async def fn(ctx):
        enemy = await _fight(ctx, hero, "creature.goblin", zone="near", first="hero")
        combat._begin_hero_turn(ctx, ctx.world.characters[hero])
        outcome = await execute_approach_attack(
            ctx, {"attacker_id": hero, "target_id": enemy, "attack": "item.no_such_weapon"}, "bad-attack"
        )
        assert not outcome["completed"]
        assert outcome["movement"]["moved_ft"] > 0
        assert combat.current_id(ctx) == hero
        assert combat.state(ctx)["deadline"] is not None
        assert not attacks(ctx, hero)
        return outcome["notes"]

    notes = play(settings, cid, [10, 10], fn)
    assert "атака не выполнена" in " ".join(notes)


def test_shove_prone_is_contested_and_consumes_single_attack(game):
    """One attack is spent; a winning Athletics contest imposes prone."""
    settings, cid, hero = game

    async def fn(ctx):
        goblin = await _fight(ctx, hero, "creature.goblin", zone="melee", first="hero")
        result = await call(
            ctx, "resolve_shove", {"attacker_id": hero, "target_id": goblin, "technique": "prone"}
        )
        assert result["ok"], result
        assert result["result"]["success"]
        assert len([e for e in ctx.events if e.tool == "resolve_shove"]) == 1
        assert any(rec.id == "condition.prone" for _, rec in ctx.world.actor(goblin).effects)
        again = await call(ctx, "resolve_shove", {"attacker_id": hero, "target_id": goblin, "technique": "prone"})
        assert not again["ok"] and "действие" in again["error"]
        return result["result"]

    outcome = play(settings, cid, [10, 10, 18, 1], fn)
    assert outcome["attacker_total"] > outcome["defender_total"]


def test_shove_push_moves_target_one_cell_without_damage(game):
    """A push uses actual grid coordinates and cannot conjure bonus damage."""
    from app.core.positions import pos_of

    settings, cid, hero = game

    async def fn(ctx):
        goblin = await _fight(ctx, hero, "creature.goblin", zone="melee", first="hero")
        source = pos_of(ctx.world, hero).cell
        before = pos_of(ctx.world, goblin).cell
        assert source is not None and before is not None
        result = await call(ctx, "resolve_shove", {"attacker_id": hero, "target_id": goblin, "technique": "push"})
        assert result["ok"], result
        row = result["result"]
        assert row["success"] and "damage" not in row
        after = pos_of(ctx.world, goblin).cell
        dx = (before[0] > source[0]) - (before[0] < source[0])
        dy = (before[1] > source[1]) - (before[1] < source[1])
        assert after == (before[0] + dx, before[1] + dy)
        assert list(after) == row["cell"]

    play(settings, cid, [10, 10, 18, 1], fn)


def test_failed_shove_and_out_of_reach_preserve_rules(game):
    settings, cid, hero = game

    async def fn(ctx):
        goblin = await _fight(ctx, hero, "creature.goblin", zone="melee", first="hero")
        failed = await call(ctx, "resolve_shove", {"attacker_id": hero, "target_id": goblin, "technique": "prone"})
        assert failed["ok"] and not failed["result"]["success"]
        assert not any(rec.id == "condition.prone" for _, rec in ctx.world.actor(goblin).effects)
        return failed["result"]

    row = play(settings, cid, [10, 10, 1, 20], fn)
    assert row["attacker_total"] <= row["defender_total"]


def test_feature_flags_refuse_unsupported_class_without_burning_attack(game):
    settings, cid, hero = game

    async def fn(ctx):
        goblin = await _fight(ctx, hero, "creature.goblin", zone="melee", first="hero")
        club = next(at for at in ctx.world.actor(hero).attacks if at["kind"] == "melee")
        args = {"attacker_id": hero, "target_id": goblin, "attack": club.get("inventory_id") or club["key"]}
        denied = await call(ctx, "resolve_attack", {**args, "reckless": True})
        assert not denied["ok"] and "умение варвара" in denied["error"]
        denied_stun = await call(ctx, "resolve_attack", {**args, "stunning_strike": True})
        assert not denied_stun["ok"] and "умение монаха" in denied_stun["error"]
        legitimate = await call(ctx, "resolve_attack", args)
        assert legitimate["ok"]
        return legitimate

    assert play(settings, cid, [10, 10, 12, 3], fn)["ok"]
