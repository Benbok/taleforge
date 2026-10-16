from types import SimpleNamespace

from app.core import combat
from app.core.characters import public_view
from app.core.companions import bring_companions, companion_record, companions_for_hero, public_companion
from tests.test_tools import call, play

pytest_plugins = ("tests.test_tools",)


def _entity(**state):
    return SimpleNamespace(
        id=state.pop("id", "en_corvin"),
        name=state.pop("name", "Корвин"),
        kind="creature",
        state=state,
        location_id="loc_maze",
        zone="far",
    )


def test_companion_record_is_read_from_entity_state():
    npc = _entity(companion={"of": "ch_hero", "since_event": "ev_join", "reason": "подхватил и повёл"})

    assert companion_record(npc) == {
        "of": "ch_hero",
        "since_event": "ev_join",
        "reason": "подхватил и повёл",
    }


def test_companions_for_hero_excludes_dead_fled_and_hostile_entities():
    world = SimpleNamespace(
        entities={
            "en_ok": _entity(id="en_ok", companion={"of": "ch_hero"}, attitude="friendly"),
            "en_dead": _entity(id="en_dead", companion={"of": "ch_hero"}, dead=True),
            "en_fled": _entity(id="en_fled", companion={"of": "ch_hero"}, fled=True),
            "en_enemy": _entity(id="en_enemy", companion={"of": "ch_hero"}, attitude="hostile"),
            "en_other": _entity(id="en_other", companion={"of": "ch_other"}, attitude="friendly"),
        },
    )

    assert [e.id for e in companions_for_hero(world, "ch_hero")] == ["en_ok"]


def test_public_companion_contains_only_table_data():
    npc = _entity(
        companion={"of": "ch_hero", "since_event": "ev_join", "reason": "секрет"},
        hp=4,
        hp_max=7,
        dead=False,
    )

    assert public_companion(npc) == {
        "id": "en_corvin",
        "name": "Корвин",
        "hp": 4,
        "hp_max": 7,
        "down": False,
        "dead": False,
    }


def test_join_party_accepts_current_hero_basis_event(game):
    settings, campaign_id, hero_id = game

    async def scenario(ctx):
        spawned = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Корвин", "attitude": "neutral"},
        )
        assert spawned["ok"], spawned
        entity_id = spawned["result"]["spawned"][0]["id"]
        basis = await ctx.record(
            "roll_check",
            actor_id=hero_id,
            target_id=entity_id,
            payload={"kind": "check", "stat": "persuasion", "success": True},
        )
        joined = await call(
            ctx,
            "join_party",
            {"entity_id": entity_id, "hero_id": hero_id, "basis_event_id": basis.id, "reason": "подхватил"},
        )
        return entity_id, joined

    entity_id, joined = play(settings, campaign_id, [], scenario)
    assert joined["ok"], joined
    assert joined["result"]["entity_id"] == entity_id


def test_join_party_rejects_foreign_or_failed_basis(game):
    settings, campaign_id, hero_id = game

    async def scenario(ctx):
        spawned = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Корвин", "attitude": "neutral"},
        )
        entity_id = spawned["result"]["spawned"][0]["id"]
        foreign = await ctx.record(
            "roll_check",
            actor_id="ch_foreign",
            target_id=entity_id,
            payload={"kind": "check", "stat": "persuasion", "success": True},
        )
        failed = await ctx.record(
            "roll_check",
            actor_id=hero_id,
            target_id=entity_id,
            payload={"kind": "check", "stat": "persuasion", "success": False},
        )
        first = await call(
            ctx,
            "join_party",
            {"entity_id": entity_id, "hero_id": hero_id, "basis_event_id": foreign.id, "reason": "подхватил"},
        )
        second = await call(
            ctx,
            "join_party",
            {"entity_id": entity_id, "hero_id": hero_id, "basis_event_id": failed.id, "reason": "подхватил"},
        )
        return first, second, ctx.world.entities[entity_id].state

    first, second, state = play(settings, campaign_id, [], scenario)
    assert not first["ok"] and not second["ok"]
    assert "companion" not in state


def test_leave_party_removes_link_and_requires_betrayal_reference(game):
    settings, campaign_id, hero_id = game

    async def scenario(ctx):
        spawned = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Корвин", "attitude": "neutral"},
        )
        entity_id = spawned["result"]["spawned"][0]["id"]
        basis = await ctx.record(
            "roll_check",
            actor_id=hero_id,
            target_id=entity_id,
            payload={"kind": "check", "stat": "persuasion", "success": True},
        )
        joined = await call(
            ctx,
            "join_party",
            {"entity_id": entity_id, "hero_id": hero_id, "basis_event_id": basis.id, "reason": "подхватил"},
        )
        betrayal = await call(
            ctx,
            "leave_party",
            {"entity_id": entity_id, "reason": "замысел", "turn_hostile": True},
        )
        left = await call(ctx, "leave_party", {"entity_id": entity_id, "reason": "ушёл своей дорогой"})
        return joined, betrayal, left, ctx.world.entities[entity_id].state

    joined, betrayal, left, state = play(settings, campaign_id, [], scenario)
    assert joined["ok"]
    assert not betrayal["ok"]
    assert left["ok"]
    assert "companion" not in state


def test_public_hero_view_contains_companions_without_relationship_secrets(game):
    settings, campaign_id, hero_id = game

    async def scenario(ctx):
        spawned = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Корвин", "attitude": "neutral"},
        )
        entity_id = spawned["result"]["spawned"][0]["id"]
        basis = await ctx.record(
            "roll_check",
            actor_id=hero_id,
            target_id=entity_id,
            payload={"kind": "check", "stat": "persuasion", "success": True},
        )
        joined = await call(
            ctx,
            "join_party",
            {"entity_id": entity_id, "hero_id": hero_id, "basis_event_id": basis.id, "reason": "секретный мотив"},
        )
        assert joined["ok"]
        return public_view(ctx.world.characters[hero_id], ctx.world.entities.values())

    view = play(settings, campaign_id, [], scenario)
    assert view["companions"] == [
        {"id": view["companions"][0]["id"], "name": "Корвин", "hp": 7, "hp_max": 7, "down": False, "dead": False}
    ]
    assert "reason" not in view["companions"][0]


def test_bring_companions_moves_only_departing_heroes_and_resets_geometry():
    hero = SimpleNamespace(id="ch_hero", location_id="loc_old")
    other = SimpleNamespace(id="ch_other", location_id="loc_old")
    npc = _entity(
        id="en_corvin",
        companion={"of": "ch_hero"},
        attitude="friendly",
        cell=[3, 4],
        bearing="s",
        cover="half",
        elevation="high",
    )
    npc.location_id = "loc_old"
    npc.zone = "far"
    world = SimpleNamespace(
        entities={npc.id: npc}, scene=SimpleNamespace(location_id="loc_old"), invalidate=lambda _: None
    )
    inverse = []

    moved = bring_companions(world, [hero], SimpleNamespace(id="loc_new"), inverse)

    assert moved == [npc]
    assert npc.location_id == "loc_new"
    assert npc.zone == "near"
    assert all(key not in npc.state for key in ("cell", "bearing", "cover", "elevation"))
    assert inverse and inverse[0]["before"]["companion"]["of"] == "ch_hero"
    assert companions_for_hero(world, other.id) == []


def test_move_tool_brings_companion_with_hero(game):
    settings, campaign_id, hero_id = game

    async def scenario(ctx):
        old = await call(ctx, "create_location", {"name": "Лабиринт", "make_current": True})
        assert old["ok"], old
        spawned = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Корвин", "attitude": "neutral"},
        )
        entity_id = spawned["result"]["spawned"][0]["id"]
        basis = await ctx.record(
            "roll_check",
            actor_id=hero_id,
            target_id=entity_id,
            payload={"kind": "check", "stat": "persuasion", "success": True},
        )
        assert (
            await call(
                ctx,
                "join_party",
                {"entity_id": entity_id, "hero_id": hero_id, "basis_event_id": basis.id, "reason": "подхватил"},
            )
        )["ok"]
        target = await call(ctx, "create_location", {"name": "Развилка", "link_to": [old["result"]["location_id"]]})
        assert target["ok"], target
        moved = await call(
            ctx,
            "move",
            {"character_ids": [hero_id], "location_id": target["result"]["location_id"]},
        )
        return moved, target["result"]["location_id"], ctx.world.entities[entity_id]

    moved, destination, entity = play(settings, campaign_id, [], scenario)
    assert moved["ok"], moved
    assert entity.location_id == destination
    assert entity.zone == "near"


def test_companion_is_nested_under_hero_in_public_order():
    hero = SimpleNamespace(id="ch_hero", name="Пупкинатор", seat_id="seat", resources={"hp": 8})
    npc = _entity(
        id="en_corvin",
        companion={"of": "ch_hero", "since_event": "ev_join", "reason": "секрет"},
        attitude="friendly",
        hp=4,
        hp_max=7,
    )
    order = combat.public_order([{"id": "ch_hero", "initiative": 12}], {hero.id: hero}, {npc.id: npc})

    assert [entry["id"] for entry in order] == ["ch_hero"]
    assert order[0]["companions"][0]["id"] == "en_corvin"
    assert "reason" not in order[0]["companions"][0]


def test_companion_does_not_get_a_separate_initiative_slot(game):
    settings, campaign_id, hero_id = game

    async def scenario(ctx):
        companion = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Корвин", "attitude": "neutral"},
        )
        companion_id = companion["result"]["spawned"][0]["id"]
        basis = await ctx.record(
            "roll_check",
            actor_id=hero_id,
            target_id=companion_id,
            payload={"kind": "check", "stat": "persuasion", "success": True},
        )
        assert (
            await call(
                ctx,
                "join_party",
                {"entity_id": companion_id, "hero_id": hero_id, "basis_event_id": basis.id, "reason": "подхватил"},
            )
        )["ok"]
        enemy = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Враг", "attitude": "hostile"},
        )
        enemy_id = enemy["result"]["spawned"][0]["id"]
        combat_started = await call(
            ctx,
            "set_scene_mode",
            {"mode": "combat", "participants": [hero_id, companion_id, enemy_id]},
        )
        return combat_started, companion_id, [entry["id"] for entry in ctx.world.scene.turn_order]

    started, companion_id, order = play(settings, campaign_id, [], scenario)
    assert started["ok"], started
    assert hero_id in order
    assert companion_id not in order


def test_companion_attack_has_its_own_action_and_cannot_repeat(game):
    settings, campaign_id, hero_id = game

    async def scenario(ctx):
        companion = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Корвин", "attitude": "neutral", "zone": "melee"},
        )
        companion_id = companion["result"]["spawned"][0]["id"]
        basis = await ctx.record(
            "roll_check",
            actor_id=hero_id,
            target_id=companion_id,
            payload={"kind": "check", "stat": "persuasion", "success": True},
        )
        assert (
            await call(
                ctx,
                "join_party",
                {"entity_id": companion_id, "hero_id": hero_id, "basis_event_id": basis.id, "reason": "подхватил"},
            )
        )["ok"]
        enemy = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Враг", "attitude": "hostile", "zone": "melee"},
        )
        enemy_id = enemy["result"]["spawned"][0]["id"]
        assert (
            await call(
                ctx,
                "set_scene_mode",
                {"mode": "combat", "participants": [hero_id, companion_id, enemy_id]},
            )
        )["ok"]
        ctx.world.scene.state = {**ctx.world.scene.state, "turn": 0, "actor": hero_id}
        attack = {"attacker_id": companion_id, "target_id": enemy_id, "attack": "shortbow"}
        first = await call(ctx, "resolve_attack", attack)
        second = await call(ctx, "resolve_attack", attack)
        return first, second, ctx.world.scene.state

    first, second, state = play(settings, campaign_id, [1, 1], scenario)
    assert first["ok"], first
    assert not second["ok"]
    assert state["spent"][next(key for key in state["spent"] if key.startswith("en_"))]["actions"] == 1


def test_enemy_target_selection_includes_companion(game):
    settings, campaign_id, hero_id = game

    async def scenario(ctx):
        companion = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Корвин", "attitude": "neutral"},
        )
        companion_id = companion["result"]["spawned"][0]["id"]
        basis = await ctx.record(
            "roll_check",
            actor_id=hero_id,
            target_id=companion_id,
            payload={"kind": "check", "stat": "persuasion", "success": True},
        )
        assert (
            await call(
                ctx,
                "join_party",
                {"entity_id": companion_id, "hero_id": hero_id, "basis_event_id": basis.id, "reason": "подхватил"},
            )
        )["ok"]
        enemy = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Враг", "attitude": "hostile"},
        )
        enemy_id = enemy["result"]["spawned"][0]["id"]
        assert (await call(ctx, "set_scene_mode", {"mode": "combat", "participants": [hero_id, enemy_id]}))["ok"]
        ctx.world.entities[companion_id].state = {**ctx.world.entities[companion_id].state, "hp": 1}
        ctx.world.characters[hero_id].resources = {**ctx.world.characters[hero_id].resources, "hp": 10}
        ctx.world.invalidate(companion_id)
        ctx.world.invalidate(hero_id)
        target = combat._pick_target(ctx, ctx.world.actor(enemy_id))
        return target.id if target else None, companion_id

    target_id, companion_id = play(settings, campaign_id, [], scenario)
    assert target_id == companion_id


def test_betrayal_inserts_former_companion_into_live_initiative(game):
    settings, campaign_id, hero_id = game

    async def scenario(ctx):
        companion = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Корвин", "attitude": "neutral"},
        )
        companion_id = companion["result"]["spawned"][0]["id"]
        basis = await ctx.record(
            "roll_check",
            actor_id=hero_id,
            target_id=companion_id,
            payload={"kind": "check", "stat": "persuasion", "success": True},
        )
        joined = await call(
            ctx,
            "join_party",
            {"entity_id": companion_id, "hero_id": hero_id, "basis_event_id": basis.id, "reason": "повёл"},
        )
        assert joined["ok"]
        enemy = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Враг", "attitude": "hostile"},
        )
        enemy_id = enemy["result"]["spawned"][0]["id"]
        assert (await call(ctx, "set_scene_mode", {"mode": "combat", "participants": [hero_id, enemy_id]}))["ok"]
        ctx.world.entities[companion_id].state = {**ctx.world.entities[companion_id].state, "plot_id": "plot_betrayal"}
        result = await call(
            ctx,
            "leave_party",
            {"entity_id": companion_id, "reason": "сигнал", "turn_hostile": True, "plot_id": "plot_betrayal"},
        )
        return result, companion_id, [entry["id"] for entry in ctx.world.scene.turn_order], combat.current_id(ctx)

    result, companion_id, order, current = play(settings, campaign_id, [], scenario)
    assert result["ok"], result
    assert companion_id in order
    assert current in order


def test_companion_link_breaks_after_entity_becomes_hostile(game):
    settings, campaign_id, hero_id = game

    async def scenario(ctx):
        spawned = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Корвин", "attitude": "neutral"},
        )
        entity_id = spawned["result"]["spawned"][0]["id"]
        basis = await ctx.record(
            "roll_check",
            actor_id=hero_id,
            target_id=entity_id,
            payload={"kind": "check", "stat": "persuasion", "success": True},
        )
        joined = await call(
            ctx,
            "join_party",
            {"entity_id": entity_id, "hero_id": hero_id, "basis_event_id": basis.id, "reason": "повёл"},
        )
        assert joined["ok"]
        changed = await call(ctx, "update_entity", {"entity_id": entity_id, "attitude": "hostile"})
        return changed, ctx.world.entities[entity_id].state, [e.tool for e in ctx.events]

    changed, state, tools = play(settings, campaign_id, [], scenario)
    assert changed["ok"], changed
    assert "companion" not in state
    assert "companion_break" in tools


def test_companion_link_breaks_after_entity_flees(game):
    settings, campaign_id, hero_id = game

    async def scenario(ctx):
        spawned = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Корвин", "attitude": "neutral"},
        )
        entity_id = spawned["result"]["spawned"][0]["id"]
        basis = await ctx.record(
            "roll_check",
            actor_id=hero_id,
            target_id=entity_id,
            payload={"kind": "check", "stat": "persuasion", "success": True},
        )
        joined = await call(
            ctx,
            "join_party",
            {"entity_id": entity_id, "hero_id": hero_id, "basis_event_id": basis.id, "reason": "повёл"},
        )
        assert joined["ok"]
        fled = await call(ctx, "update_entity", {"entity_id": entity_id, "fled": True})
        return fled, ctx.world.entities[entity_id].state

    fled, state = play(settings, campaign_id, [], scenario)
    assert fled["ok"], fled
    assert "companion" not in state


def test_scene_table_lists_companion_without_relationship_secret(game):
    settings, campaign_id, hero_id = game

    async def scenario(ctx):
        spawned = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Корвин", "attitude": "neutral"},
        )
        entity_id = spawned["result"]["spawned"][0]["id"]
        basis = await ctx.record(
            "roll_check",
            actor_id=hero_id,
            target_id=entity_id,
            payload={"kind": "check", "stat": "persuasion", "success": True},
        )
        joined = await call(
            ctx,
            "join_party",
            {"entity_id": entity_id, "hero_id": hero_id, "basis_event_id": basis.id, "reason": "подхватил"},
        )
        assert joined["ok"]
        return ctx.world.scene_table()

    table = play(settings, campaign_id, [], scenario)
    assert "Спутники:" in table
    assert "Корвин" in table
    assert "plot_id" not in table
