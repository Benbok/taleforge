import asyncio
import json

from sqlalchemy import select

from app.agents.master.service import MasterService
from app.db.models import Event, HeroAbility, MasterTurn, Message
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup


def proposal():
    return dict(
        schema_version=2,
        name="Искры",
        source="supernatural",
        resolution="automatic",
        intensity="light",
        effects=[{"kind": "cosmetic"}],
    )


def test_fresh_v2_magic_has_real_cost_learning_and_automatic_card(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                proposal(),
                {"verdict": "pass", "covered_requirements": []},
                "Искры мягко мерцают над ладонью.",
                {"verdict": "pass"},
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace
            assert len(list(await s.scalars(select(HeroAbility)))) == 1
            card = await s.scalar(select(Message).where(Message.kind == "roll"))
            assert card and card.data["universal_proof"]["cost"] == "1"
            assert card.data["universal_proof"]["draws"] == []
            assert card.data["universal_proof"]["source_kind"] == "supernatural"
        assert "HIDDEN-SECRET" not in json.dumps(provider.prompts[-2:])
        await engine.dispose()

    asyncio.run(run())


def test_fresh_legacy_proposal_cannot_bypass_review_or_spend(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                {"kind": "ability", "profile": {"id": "bad", "kind": "check", "attribute": "wis"}},
                {"kind": "ordinary_check"},
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            assert list(await s.scalars(select(Event))) == []
            turn = await s.get(MasterTurn, tid)
            assert turn.trace["proposal_attempts"]["source"] == 2
        await engine.dispose()

    asyncio.run(run())


def test_mismatch_review_does_not_roll_and_budget_is_durable(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [proposal(), {"verdict": "mismatch", "message": "Нужна форма, а не искры."}, RuntimeError("offline")]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        await MasterService(maker, Bus(), Provider([])).run_turn("c")
        async with maker() as s:
            assert list(await s.scalars(select(Event))) == []
            assert (await s.get(MasterTurn, tid)).trace["proposal_attempts"]["source"] == 2
        await engine.dispose()

    asyncio.run(run())


def test_unrealized_narrative_effects_fall_back_without_repeating_magic(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                proposal(),
                {"verdict": "pass"},
                "Герой стал неуязвимым кустом.",
                {"verdict": "mismatch", "message": "Не применялась форма."},
                "Появилась золотая кружка.",
                {"verdict": "mismatch", "message": "Не создан предмет."},
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace
            message = await s.get(Message, turn.narration_message_id)
            assert "неуязвим" not in message.content and "золотая" not in message.content
            assert len(list(await s.scalars(select(Event)))) == 1
            assert turn.trace["exploration_narration"]["attempts"] == 2
        await engine.dispose()

    asyncio.run(run())
