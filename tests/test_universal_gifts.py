import asyncio

import pytest

from app.core.campaigns import AccessDenied
from app.core.universal.exploration_resolution import resolve_exploration
from app.core.universal.gifts import gift_bonus
from app.core.universal.inventory import create_item, owned_items, state_of, store
from app.core.universal.resolution import ResolutionContext
from app.db.models import Entity
from app.rules.dice import FixedDice
from app.rules.universal.items import ItemProfile
from app.rules.universal.profiles import CheckNarration
from tests.test_universal_loot import loot_action
from tests.test_universal_resolution import setup


async def gift_setup(s, status="common", owner="hero", equipped=False):
    npc = Entity(id="npc", campaign_id="c", kind="creature", name="Проводник", state={"hostile": False})
    s.add(npc)
    await s.flush()
    item = await create_item(
        s, "c", owner, ItemProfile(name="Куртка", kind="armor", status=status), "gift", equipped=equipped
    )
    return npc, item


def test_speech_check_preserves_an_ordinary_vessel_transfer_between_heroes(tmp_path):
    from app.core.universal.objects import ObjectState, object_state

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            cup = Entity(
                id="cup",
                campaign_id="c",
                kind="object",
                name="Кружка",
                state={"exploration": ObjectState(template="vessel", owner_id="hero").model_dump(mode="json")},
            )
            s.add(cup)
            await s.flush()
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20]))
            a = await offer(s, ctx, cup)
            operations = [op.model_copy(update={"recipient_id": "target"}) for op in a.operations]
            a = a.model_copy(
                update={"operations": operations, "definition": a.definition.model_copy(update={"effects": operations})}
            )
            from app.rules.universal.exploration import definition_key

            a.definition.id = definition_key(a.definition)
            assert await gift_bonus(ctx, a) == 0
            result = await resolve_exploration(ctx, a, "offer")
            assert result.success and object_state(await s.get(Entity, "cup")).owner_id == "target"
        await engine.dispose()

    asyncio.run(run())


async def offer(s, ctx, item, mid="offer", speak=True, resolution="check", **kwargs):
    effects = [dict(kind="give", object_id=item.id, recipient_id="npc")]
    if speak:
        effects.append(dict(kind="speak", recipient_id="npc"))
    from app.core.chat import next_seq
    from app.core.universal.interpretation import compile_exploration
    from app.db.models import Message
    from app.rules.universal.exploration import IntentReview, IntentV2

    s.add(
        Message(
            id=mid,
            campaign_id="c",
            seq=await next_seq(s, "c"),
            seat_id=ctx.seat_id,
            author_user_id="u",
            kind="action",
            content="Дарю куртку и прошу помочь.",
        )
    )
    await s.flush()
    intent = IntentV2(
        source="mundane",
        resolution=resolution,
        effects=effects,
        attribute="cha",
        difficulty=12,
        check_outcomes=CheckNarration(
            success="Помогает.",
            failure="Отказывает.",
            critical_success="Охотно помогает.",
            critical_failure="Сердится.",
        )
        if resolution == "check"
        else None,
        **kwargs,
    )
    return await compile_exploration(
        ctx,
        intent,
        IntentReview(verdict="pass"),
        dict(source_message_id=mid, source_text="Дарю куртку и прошу помочь.", evidence=""),
    )


@pytest.mark.parametrize("status,bonus", [("common", 2), ("rare", 3), ("unique", 4), ("epic", 4)])
def test_gift_moves_gear_to_creature_and_adds_one_bonus(tmp_path, status, bonus):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            _, item = await gift_setup(s, status)
            item_id = item.id
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([9]))
            a = await offer(s, ctx, item)
            assert await gift_bonus(ctx, a) == bonus
            result = await resolve_exploration(ctx, a, "offer")
            assert result.success and result.total == 11 + bonus
            assert result.checks[0].modifier == 2 + bonus
            assert not await owned_items(s, "c", "hero")
            assert state_of(await s.get(Entity, item_id)).quantity == 0
            assert (await s.get(Entity, "npc")).state["gifts"] == ["Куртка"]
            assert any(c.kind == "item_given" for c in result.changes)
            assert (await resolve_exploration(ctx, a, "offer")).status == "repeated"
            assert (await s.get(Entity, "npc")).state["gifts"] == ["Куртка"]
        await engine.dispose()

    asyncio.run(run())


def test_bonus_is_capped_and_requires_a_speak_check(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            _, item = await gift_setup(s)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            a = await offer(s, ctx, item)
            from app.rules.universal.exploration import EffectIntentV2

            gifts = []
            for i in range(3):
                other = await create_item(s, "c", "hero", ItemProfile(name="Дар", kind="armor"), f"extra{i}")
                gifts.append(EffectIntentV2(kind="give", object_id=other.id, recipient_id="npc"))
            assert await gift_bonus(ctx, a.model_copy(update={"operations": gifts + a.operations})) == 4
            assert await gift_bonus(ctx, a.model_copy(update={"operations": gifts})) == 0
            assert await gift_bonus(ctx, a.model_copy(update={"resolution": "automatic"})) == 0
            assert (
                await gift_bonus(ctx, a.model_copy(update={"operations": [a.operations[0]] * 3 + a.operations[1:]}))
                == 2
            )
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("roll", [7, 9])
def test_investment_offer_and_execution_both_include_the_gift(tmp_path, roll):
    from app.core.universal.investment import make_offer
    from app.core.universal.profiles import load_actor
    from app.db.models import GameSession

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            _, item = await gift_setup(s)
            s.add(GameSession(id="game", campaign_id="c"))
            await s.flush()
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]), preroll=(roll,), invest=roll == 7)
            a = await offer(s, ctx, item)
            sheet, resources = await load_actor(s, "c", "hero")
            card = await make_offer(s, "c", "game", None, a, sheet, resources, [roll], None, "seat")
            if roll == 9:
                assert card is None
            else:
                assert card.data["price"] == 3 and card.data["shortfall"] == 1 and card.data["total"] == 11
                result = await resolve_exploration(ctx, a, "offer")
                assert result.success and result.total == 12 and result.cost == 5  # 3 invested + 2 for the difficulty
                assert result.checks[0].invested == 1
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "reason",
    ["hostile", "remote", "equipped", "foreign", "missing", "empty", "no_recipient", "not_creature", "duplicate"],
)
def test_refused_gifts_do_not_consume_items_or_dice(tmp_path, reason):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            npc, item = await gift_setup(
                s, owner="target" if reason == "foreign" else "hero", equipped=reason == "equipped"
            )
            if reason == "hostile":
                npc.state = {"hostile": True}
            if reason == "remote":
                s.add(Entity(id="away", campaign_id="c", kind="location", name="Даль"))
                await s.flush()
                npc.location_id = "away"
            if reason == "not_creature":
                npc.kind = "object"
            if reason == "empty":
                store(item, state_of(item).model_copy(update={"quantity": 0}))
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            effect = dict(
                kind="give",
                object_id="absent" if reason == "missing" else item.id,
                recipient_id=None if reason == "no_recipient" else "npc",
            )
            with pytest.raises((ValueError, AccessDenied)):
                if reason == "duplicate":
                    await loot_action(s, ctx, [effect, effect])
                await loot_action(s, ctx, [effect])
            assert state_of(item).quantity == (0 if reason == "empty" else 1)
        await engine.dispose()

    asyncio.run(run())
