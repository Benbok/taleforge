import asyncio

from sqlalchemy import select

from app.agents.master.service import MasterService
from app.core.universal.action_intents import ActionIntent
from app.core.universal.preparation import prepare_action
from app.core.universal.resolution import ResolutionContext, resolve_action
from app.core.universal.rolls import ensure_roll_message
from app.db.models import Event, MasterTurn, Message
from app.rules.dice import FixedDice
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup


def test_roll_card_is_actual_saved_evidence_and_survives_narrator_restart(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                dict(
                    kind="ordinary_check",
                    attribute="wis",
                    difficulty=12,
                    check_outcomes=dict(success="Различимы шаги.", failure="Звуки неразличимы."),
                ),
                RuntimeError("offline"),
            ]
        )
        tid = await MasterService(maker, Bus(), provider, dice_factory=lambda: FixedDice([9])).run_turn("c")
        async with maker() as s:
            cards = list(await s.scalars(select(Message).where(Message.kind == "roll")))
            assert len(cards) == 1
            proof = cards[0].data["universal_proof"]
            assert proof["draws"] == [{"sides": 20, "value": 9}]
            check = proof["checks"][0]
            assert (check["natural"], check["modifier"], check["total"], check["difficulty"]) == (9, "2", "11", "12")
            assert check["success"] is False
            assert proof["cost"] == "0"
            assert cards[0].seq == 2
        await MasterService(maker, Bus(), Provider(["Искра гаснет."]), dice_factory=lambda: FixedDice([])).run_turn("c")
        async with maker() as s:
            assert (await s.get(MasterTurn, tid)).status == "done"
            assert len(list(await s.scalars(select(Message).where(Message.kind == "roll")))) == 1
            assert len(list(await s.scalars(select(Event)))) == 1
        await engine.dispose()

    asyncio.run(run())


def test_attack_card_keeps_real_damage_dice_but_hides_opponent_armor(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([15, 3]))
            compiled = await prepare_action(
                ctx, ActionIntent(kind="ability", effect="damage", targets=["target"]), "attack"
            )
            result = await resolve_action(ctx, compiled.proposal, "attack")
            card = await ensure_roll_message(s, "c", "game", None, "attack", ["seat"])
            proof = card.data["universal_proof"]
            assert proof["draws"] == [{"sides": 20, "value": 15}, {"sides": 6, "value": 3}]
            assert proof["checks"][0]["difficulty"] is None
            assert proof["damage"] == str(result.damage)
            assert card.visible_to == ["seat"]
        await engine.dispose()

    asyncio.run(run())


def test_multi_target_receipt_keeps_each_check_and_die(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([9, 15]))
            compiled = await prepare_action(
                ctx,
                ActionIntent(
                    kind="ability",
                    attribute="wis",
                    effect="check",
                    difficulty=12,
                    targets=["hero", "target"],
                    target_scope="actors",
                ),
                "two",
            )
            result = await resolve_action(ctx, compiled.proposal, "two")
            assert [c.total for c in result.checks] == [11, 17]
            assert [c.success for c in result.checks] == [False, True]
            assert [d.value for d in result.draws] == [9, 15]
        await engine.dispose()

    asyncio.run(run())
