import asyncio

from sqlalchemy import select

from app.agents.master.service import MasterService
from app.core.universal.profiles import load_actor
from app.db.models import Event, LlmCall, MasterTurn, Message, RuntimeProfile
from app.rules.dice import FixedDice
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup


def test_provider_failure_is_saved_audited_and_published_on_first_attempt(tmp_path):
    class RecordingBus(Bus):
        def __init__(self):
            self.events = []

        async def publish(self, cid, event, audience):
            self.events.append(event)

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        bus = RecordingBus()
        await MasterService(maker, bus, Provider([RuntimeError("private provider details")])).run_turn("c")
        async with maker() as s:
            source = await s.get(Message, "source")
            failure = source.data["action_failure"]
            assert failure["category"] == "internal_error"
            assert "private" not in failure["message"]
            calls = list(await s.scalars(select(LlmCall)))
            assert len(calls) == 1 and calls[0].error
        source_updates = [
            e["payload"] for e in bus.events if e["type"] == "message.new" and e["payload"]["id"] == "source"
        ]
        assert source_updates[-1]["data"]["action_failure"] == failure
        await engine.dispose()

    asyncio.run(run())


def test_recovered_narration_clears_transient_notice_without_repeating_action(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        first = Provider(
            [
                dict(
                    schema_version=2,
                    source="mundane",
                    player_request="ordinary",
                    resolution="check",
                    effects=[dict(kind="observe")],
                    difficulty=1,
                    check_outcomes=dict(
                        success="Получается высечь искру.",
                        failure="Искра не появляется.",
                        critical_success="Получается высечь яркую искру с первого удара.",
                        critical_failure="Камень выскальзывает, попытка высечь искру сорвана.",
                    ),
                ),
                dict(verdict="pass"),
                RuntimeError("narrator offline"),
            ]
        )
        tid = await MasterService(maker, Bus(), first, dice_factory=lambda: FixedDice([20])).run_turn("c")
        async with maker() as s:
            assert (await s.get(Message, "source")).data["action_failure"]["code"] == "narration_unavailable"
        await MasterService(
            maker,
            Bus(),
            Provider(["Новых подтверждённых деталей не обнаружено.", dict(verdict="pass")]),
            dice_factory=lambda: FixedDice([]),
        ).run_turn("c")
        async with maker() as s:
            assert (await s.get(MasterTurn, tid)).status == "done"
            assert "action_failure" not in (await s.get(Message, "source")).data
            assert len(list(await s.scalars(select(Event)))) == 1
        await engine.dispose()

    asyncio.run(run())


def test_invalid_proposal_is_repaired_once_before_profile_is_saved(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                dict(
                    schema_version=2,
                    source="mundane",
                    player_request="ordinary",
                    resolution="automatic",
                    requirements=[dict(id="r1", quote="высечь искру", effect="observe")],
                    effects=[dict(kind="wait")],
                ),
                dict(
                    schema_version=2,
                    source="mundane",
                    player_request="ordinary",
                    resolution="check",
                    effects=[dict(kind="observe")],
                    name="Факел",
                    attribute="dex",
                    difficulty=10,
                    check_outcomes=dict(
                        success="Получается высечь искру.",
                        failure="Искра не появляется.",
                        critical_success="Получается высечь яркую искру с первого удара.",
                        critical_failure="Камень выскальзывает, попытка высечь искру сорвана.",
                    ),
                ),
                "Вы пытаетесь высечь искру.",
                dict(verdict="pass"),
            ]
        )
        tid = await MasterService(maker, Bus(), provider, dice_factory=lambda: FixedDice([14])).run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace.get("error")
            assert turn.trace["proposal_attempts"]["source"] == 2
            assert turn.trace["prepared"]["source"]["category"] == "exploration"
            assert len(list(await s.scalars(select(RuntimeProfile)))) == 0
            assert len(list(await s.scalars(select(Event)))) == 1
            assert (await load_actor(s, "c", "hero"))[1].energies["dex"] == 20
        assert len(provider.prompts) == 4
        await engine.dispose()

    asyncio.run(run())


def test_unsupported_combat_effect_is_not_a_fictional_magic_failure(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                dict(
                    schema_version=2,
                    source="supernatural",
                    resolution="automatic",
                    effects=[dict(kind="cannot_move")],
                    name="Светлячки",
                    attribute="wis",
                ),
                dict(verdict="unsupported"),
            ]
        )
        tid = await MasterService(maker, Bus(), provider, dice_factory=lambda: FixedDice([])).run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace.get("error")
            message = await s.get(Message, turn.narration_message_id)
            assert "не поддерживается движком" in message.content
            assert "пульсац" not in message.content
            assert (await s.get(Message, "source")).data["action_failure"]["category"] == "unsupported_capability"
            assert not list(await s.scalars(select(RuntimeProfile)))
            assert not list(await s.scalars(select(Event)))
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 24
        assert len(provider.prompts) == 2  # No fictional narrator call for technical refusal.
        await engine.dispose()

    asyncio.run(run())


def test_malformed_proposal_budget_survives_restart_without_infinite_calls(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        first = MasterService(maker, Bus(), Provider(["not JSON", RuntimeError("offline")]))
        tid = await first.run_turn("c")
        provider = Provider([])
        assert await MasterService(maker, Bus(), provider).run_turn("c") == tid
        assert not provider.prompts
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done"
            assert turn.trace["proposal_attempts"]["source"] == 2
            assert turn.trace["outcomes"]["source"]["failure"]["category"] == "internal_error"
            assert not list(await s.scalars(select(Event)))
        await engine.dispose()

    asyncio.run(run())
