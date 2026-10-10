# ruff: noqa: F811 — fixture imported from test_tools
"""Shillelagh: server-side item-bound magical weapon mechanics (SRD 5.1)."""

from app.core import weapon_enchantments as ench
from tests.test_tools import call, game, play  # noqa: F401


async def _make_druid(ctx, hero):
    ch = ctx.world.characters[hero]
    ch.sheet = {**(ch.sheet or {}), "class_id": "class.druid", "cantrips": ["spell.shillelagh"]}
    ctx.world.invalidate(hero)


async def _weapon(ctx, hero, template):
    result = await call(ctx, "give_item", {
        "character_id": hero, "item_template_id": template, "reason": "test",
    })
    assert result["ok"], result
    inv_id = result["result"]["inventory_id"]
    equipped = await call(ctx, "equip_item", {"character_id": hero, "inventory_id": inv_id, "equipped": True})
    assert equipped["ok"], equipped
    return inv_id


def _attack(ctx, hero, inv_id):
    return next(a for a in ctx.world.actor(hero).attacks if a.get("inventory_id") == inv_id)


def test_shillelagh_improves_only_held_club_and_preserves_proficiency(game):
    settings, cid, hero = game

    async def fn(ctx):
        await _make_druid(ctx, hero)
        first = await _weapon(ctx, hero, "item.club")
        second = await _weapon(ctx, hero, "item.quarterstaff")
        before = dict(_attack(ctx, hero, first))
        other = dict(_attack(ctx, hero, second))
        cast = await call(ctx, "cast_spell", {
            "caster_id": hero, "spell_id": "spell.shillelagh", "weapon_id": first,
        })
        assert cast["ok"], cast
        assert cast["result"]["enchantment"] == {
            "weapon_id": first, "damage_die": "1d8", "magical": True,
        }
        att = _attack(ctx, hero, first)
        mods = ctx.world.actor(hero).mods
        assert att["attack_bonus"] == before["attack_bonus"] - mods["str"] + mods["wis"]
        assert att["damage"].startswith(f"1d8{mods['wis']:+d}")
        assert att["ability"] == "wis"
        assert att["magical"] is True
        assert _attack(ctx, hero, second) == other
        assert ctx.world.characters[hero].resources[ench.SHILLELAGH]["inventory_id"] == first
        return first

    assert play(settings, cid, [], fn).startswith("inv_")


def test_shillelagh_recasting_and_releasing_weapon(game):
    settings, cid, hero = game

    async def fn(ctx):
        await _make_druid(ctx, hero)
        club = await _weapon(ctx, hero, "item.club")
        staff = await _weapon(ctx, hero, "item.quarterstaff")
        first = await call(ctx, "cast_spell", {
            "caster_id": hero, "spell_id": "spell.shillelagh", "weapon_id": club,
        })
        assert first["ok"], first
        second = await call(ctx, "cast_spell", {
            "caster_id": hero, "spell_id": "spell.shillelagh", "weapon_id": staff,
        })
        assert second["ok"], second
        assert _attack(ctx, hero, club).get("magical") is None
        assert _attack(ctx, hero, staff)["magical"] is True
        release = await call(ctx, "equip_item", {"character_id": hero, "inventory_id": staff, "equipped": False})
        assert release["ok"], release
        assert ench.SHILLELAGH not in ctx.world.characters[hero].resources
        assert _attack(ctx, hero, staff).get("magical") is None
        again = await call(ctx, "equip_item", {"character_id": hero, "inventory_id": staff, "equipped": True})
        assert again["ok"], again
        assert _attack(ctx, hero, staff).get("magical") is None

    play(settings, cid, [], fn)


def test_shillelagh_expires_after_one_world_minute(game):
    settings, cid, hero = game

    async def fn(ctx):
        await _make_druid(ctx, hero)
        club = await _weapon(ctx, hero, "item.club")
        cast = await call(ctx, "cast_spell", {"caster_id": hero, "spell_id": "spell.shillelagh"})
        assert cast["ok"], cast
        assert _attack(ctx, hero, club)["magical"] is True
        tick = await call(ctx, "advance_time", {"amount": 1, "unit": "minute", "reason": "test"})
        assert tick["ok"], tick
        assert ench.SHILLELAGH not in ctx.world.characters[hero].resources
        assert _attack(ctx, hero, club).get("magical") is None

    play(settings, cid, [], fn)


def test_shillelagh_rejects_empty_hand_and_nonwooden_weapon(game):
    settings, cid, hero = game

    async def fn(ctx):
        await _make_druid(ctx, hero)
        no_weapon = await call(ctx, "cast_spell", {"caster_id": hero, "spell_id": "spell.shillelagh"})
        assert not no_weapon["ok"]
        assert "сначала возьмите" in no_weapon["error"]
        sword = await _weapon(ctx, hero, "item.longsword")
        wrong = await call(ctx, "cast_spell", {
            "caster_id": hero, "spell_id": "spell.shillelagh", "weapon_id": sword,
        })
        assert not wrong["ok"]
        assert "дубинка или боевой посох" in wrong["error"]
        assert ench.SHILLELAGH not in ctx.world.characters[hero].resources
        assert not [ev for ev in ctx.events if ev.tool == "cast_spell" and ev.actor_id == hero]

    play(settings, cid, [], fn)


def test_shillelagh_ends_when_item_is_dropped(game):
    settings, cid, hero = game

    async def fn(ctx):
        await _make_druid(ctx, hero)
        club = await _weapon(ctx, hero, "item.club")
        assert (await call(ctx, "cast_spell", {
            "caster_id": hero, "spell_id": "spell.shillelagh", "weapon_id": club,
        }))["ok"]
        result = await call(ctx, "drop_item", {"character_id": hero, "inventory_id": club})
        assert result["ok"], result
        assert ench.SHILLELAGH not in ctx.world.characters[hero].resources

    play(settings, cid, [], fn)
