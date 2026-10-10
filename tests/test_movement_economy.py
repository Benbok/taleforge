# ruff: noqa: F811 — pytest fixture name is imported by design
"""Server-owned cumulative movement and Dash action economy in combat."""

from app.core import combat, economy
from tests.test_combat import _fight
from tests.test_tools import call, game, play  # noqa: F401 — fixture game


def test_cumulative_movement_spends_dash_action(game):
    settings, cid, hero = game

    async def fn(ctx):
        await _fight(ctx, hero, "creature.goblin", zone="far", first="hero")
        combat._begin_hero_turn(ctx, ctx.world.characters[hero])
        assert economy.charge_movement(ctx, hero, 20) is False
        assert economy.moved_ft(ctx.world, hero) == 20
        assert economy.charge_movement(ctx, hero, 15) is True
        assert economy.moved_ft(ctx.world, hero) == 35
        rest = economy.view(ctx.world, hero)
        assert rest is not None and not rest["action"] and rest["move_left_ft"] == 25

    play(settings, cid, [], fn)


def test_movement_cannot_exceed_dash_without_action(game):
    settings, cid, hero = game

    async def fn(ctx):
        await _fight(ctx, hero, "creature.goblin", zone="far", first="hero")
        combat._begin_hero_turn(ctx, ctx.world.characters[hero])
        assert economy.charge_movement(ctx, hero, 30) is False
        assert economy.charge_movement(ctx, hero, 30) is True
        before = economy.moved_ft(ctx.world, hero)
        from app.tools.registry import ToolError

        try:
            economy.charge_movement(ctx, hero, 5)
        except ToolError as exc:
            assert "потрачено" in str(exc)
        else:
            raise AssertionError("movement past Dash should fail when no further action remains")
        assert economy.moved_ft(ctx.world, hero) == before
        assert economy.view(ctx.world, hero)["move_left_ft"] == 0

    play(settings, cid, [], fn)


def test_reposition_rejects_out_of_turn_character_movement(game):
    settings, cid, hero = game

    async def fn(ctx):
        await _fight(ctx, hero, "creature.goblin", zone="melee", first="creature")
        result = await call(ctx, "reposition", {"actor_id": hero, "zone": "far"})
        assert not result["ok"]
        assert "свой ход" in result["error"]
        assert economy.moved_ft(ctx.world, hero) == 0

    play(settings, cid, [], fn)


def test_reposition_uses_movement_ledger(game):
    settings, cid, hero = game

    async def fn(ctx):
        await _fight(ctx, hero, "creature.goblin", zone="far", first="hero")
        combat._begin_hero_turn(ctx, ctx.world.characters[hero])
        result = await call(ctx, "reposition", {"actor_id": hero, "zone": "near"})
        assert result["ok"], result
        moved = result["result"]["moved_ft"]
        assert moved > 0
        assert economy.moved_ft(ctx.world, hero) == moved
        assert economy.view(ctx.world, hero)["move_left_ft"] >= 0

    play(settings, cid, [], fn)
