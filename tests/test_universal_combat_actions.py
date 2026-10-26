import asyncio

import pytest

from app.core.universal.combat_actions import effective_actor
from app.core.universal.exploration_resolution import resolve_exploration
from app.core.universal.interpretation import compile_exploration
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Message
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, IntentReview, IntentV2
from tests.test_universal_resolution import setup


async def attack(s, ctx, effects, *, targets=None, resolution="attack", source="supernatural"):
    s.add(
        Message(
            id="attack", campaign_id="c", seq=1, seat_id="seat", author_user_id="u", kind="action", content="Действую"
        )
    )
    await s.flush()
    intent = IntentV2(
        name="Лоза",
        source=source,
        intensity="normal",
        resolution=resolution,
        targets=targets or ["target"],
        effects=effects,
    )
    return await compile_exploration(
        ctx, intent, IntentReview(verdict="pass"), dict(source_message_id="attack", source_text="Действую", evidence="")
    )


def test_hit_damage_and_resisted_binding_are_independent(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([15, 4, 20]))
            action = await attack(s, ctx, [EffectIntentV2(kind="damage"), EffectIntentV2(kind="cannot_move")])
            result = await resolve_exploration(ctx, action, "attack")
            assert result.status == "applied" and result.success
            assert (await s.get(Character, "target")).resources["hp"] == "16"
            assert [c.kind for c in result.changes].count("damage") == 1
            assert not (await effective_actor(s, "c", "target"))["cannot_move"]
            assert result.effect_outcomes[0].natural == 20 and not result.effect_outcomes[0].applied
            assert result.ability_ref is None
            assert (await resolve_exploration(ctx, action, "attack")).status == "repeated"
        await engine.dispose()

    asyncio.run(run())


def test_successful_control_restricts_target_and_heal_clamps(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([1]))
            action = await attack(s, ctx, [EffectIntentV2(kind="cannot_move")], resolution="automatic")
            result = await resolve_exploration(ctx, action, "attack")
            assert result.success and (await effective_actor(s, "c", "target"))["cannot_move"]
            assert not (await effective_actor(s, "c", "target"))["cannot_act"]
        await engine.dispose()

    asyncio.run(run())


def test_foreign_targets_and_free_fake_magic_reject_before_dice(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]), frozenset({"hero"}))
            with pytest.raises(ValueError):
                await attack(s, ctx, [EffectIntentV2(kind="damage")])
        await engine.dispose()

    asyncio.run(run())


def test_equipped_weapon_uses_its_hit_bonus_without_rarity_damage_twice(tmp_path):
    from app.core.universal.inventory import create_item, equip
    from app.rules.universal.items import ItemProfile

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            weapon = await create_item(
                s, "c", "hero", ItemProfile(name="Клинок", kind="weapon", status="rare", attack_bonus=1), "weapon"
            )
            await equip(s, "c", "hero", weapon.id, True, "equip")
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([12, 6]))
            action = await attack(s, ctx, [EffectIntentV2(kind="weapon_attack", object_id=weapon.id)], source="item")
            result = await resolve_exploration(ctx, action, "attack")
            assert result.success and result.total == 12 and result.cost == 0
            assert (await s.get(Character, "target")).resources["hp"] == "17"
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("roll,expected_hp,own_hp", [(20, "11", "22"), (1, "22", "21")])
def test_attack_critical_dice_and_fumble_are_real(tmp_path, roll, expected_hp, own_hp):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([roll, 4, 5]))
            action = await attack(s, ctx, [EffectIntentV2(kind="damage")])
            result = await resolve_exploration(ctx, action, "attack")
            assert result.status == "applied"
            assert (await s.get(Character, "target")).resources["hp"] == expected_hp
            assert (await s.get(Character, "hero")).resources["hp"] == own_hp
        await engine.dispose()

    asyncio.run(run())


def test_heal_clamps_to_maximum(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            target = await s.get(Character, "target")
            target.resources = {**target.resources, "hp": "20"}
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([4]))
            action = await attack(s, ctx, [EffectIntentV2(kind="heal")], resolution="automatic")
            result = await resolve_exploration(ctx, action, "attack")
            assert result.success and result.changes[0].data["amount"] == "2"
            assert target.resources["hp"] == "22"
        await engine.dispose()

    asyncio.run(run())


def test_first_attack_can_bind_a_visible_foe_from_established_scene_evidence(tmp_path):
    from app.db.models import Entity
    from app.rules.universal.exploration import IntroductionV2

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Entity(id="place", campaign_id="c", kind="location", name="Зал", description="Страж стоит у арки."))
            (await s.get(Character, "hero")).location_id = "place"
            s.add(
                Message(
                    id="first-attack",
                    campaign_id="c",
                    seq=1,
                    seat_id="seat",
                    author_user_id="u",
                    kind="action",
                    content="Атакую стража.",
                )
            )
            await s.flush()
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([15, 4]), frozenset({"hero"}))
            intent = IntentV2(
                source="supernatural",
                resolution="attack",
                intensity="normal",
                targets=["intro:guard"],
                effects=[EffectIntentV2(kind="damage")],
                introductions=[
                    IntroductionV2(ref="guard", template="observer", name="Страж", evidence_quote="Страж стоит у арки.")
                ],
            )
            action = await compile_exploration(
                ctx,
                intent,
                IntentReview(verdict="pass"),
                dict(source_message_id="first-attack", source_text="Атакую стража.", evidence="Страж стоит у арки."),
            )
            result = await resolve_exploration(ctx, action, "first-attack")
            assert result.status == "applied" and result.success
            foe = await s.get(Entity, action.targets[0])
            assert foe.state["resources"]["hp"] == "14" and foe.state["hostile"]
        await engine.dispose()

    asyncio.run(run())
