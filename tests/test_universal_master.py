import asyncio
import json

import pytest
from sqlalchemy import select

from app.agents.llm import LLMReply
from app.agents.master.service import MasterService
from app.agents.master.universal import Admission
from app.core.universal.profiles import load_actor
from app.db.models import Campaign, CampaignSecret, Event, GameSession, MasterTurn, Message, Seat
from app.rules import get_engine
from tests.test_universal_resolution import setup


def test_universal_engine_selection():
    assert type(get_engine("universal")).__name__ == "UniversalEngine"
    with pytest.raises(KeyError):
        get_engine("dnd5e")


def test_closed_admission_and_frozen_dc():
    with pytest.raises(ValueError):
        Admission.model_validate(dict(kind="check", reason="jump", difficulty=41))
    with pytest.raises(ValueError):
        Admission.model_validate(dict(kind="narrative", reason="smile", damage=100))


class Provider:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    async def complete(self, messages, **kwargs):
        self.prompts.append(messages)
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return LLMReply(text=json.dumps(result) if isinstance(result, dict) else result)


class Bus:
    async def publish(self, *args):
        pass


async def prepare(maker):
    async with maker() as s:
        s.add(Seat(id="master", campaign_id="c", role="master", position=0, occupant_type="agent"))
        s.add(GameSession(id="game", campaign_id="c"))
        s.add(
            CampaignSecret(campaign_id="c", setting={"studio": {"laws": "NO TIME TRAVEL", "private": "HIDDEN-SECRET"}})
        )
        s.add(
            Message(
                id="source",
                campaign_id="c",
                session_id="game",
                seat_id="seat",
                author_user_id="u",
                seq=1,
                kind="action",
                content="Invent a vine sight",
            )
        )
        c = await s.get(Campaign, "c")
        c.last_seq = 1
        await s.commit()


def test_paid_action_restart_preserves_receipt_and_private_boundary(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        proposal = dict(
            kind="ability",
            reason="Vine sight",
            difficulty=1,
            profile=dict(id="sight", attribute="wis", kind="check", resource_key="wis"),
        )
        first = Provider([proposal, RuntimeError("narrator down")])
        tid = await MasterService(maker, Bus(), first).run_turn("c")
        async with maker() as s:
            t = await s.get(MasterTurn, tid)
            assert t.status == "failed", t.trace
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 21
            assert len(list(await s.scalars(select(Event)))) == 1
        second = Provider(["Vines reveal the path."])
        service = MasterService(maker, Bus(), second)
        assert await service.run_turn("c") == tid
        assert await service.run_turn("c") is None
        assert "HIDDEN-SECRET" not in json.dumps(second.prompts)
        async with maker() as s:
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 21
            assert (await s.get(MasterTurn, tid)).status == "done"
            assert len(list(await s.scalars(select(Message).where(Message.kind == "narration")))) == 1
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "admission",
    [
        dict(kind="check", reason="Climb", attribute="dex", difficulty=12),
        dict(kind="denied", reason="Time travel violates the fixed world laws"),
        dict(kind="narrative", reason="The hero smiles"),
    ],
)
def test_free_and_denied_actions_preserve_energy(tmp_path, admission):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        service = MasterService(maker, Bus(), Provider([admission, admission["reason"]]))
        tid = await service.run_turn("c")
        async with maker() as s:
            t = await s.get(MasterTurn, tid)
            assert t.status == "done", t.trace.get("error")
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 24
            events = list(await s.scalars(select(Event)))
            assert len(events) == (1 if admission["kind"] == "check" else 0)
        await engine.dispose()

    asyncio.run(run())


def test_hidden_target_cannot_be_granted_by_model(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                dict(
                    kind="ability",
                    reason="SECRET private reasoning",
                    public_reason="Vines lash out",
                    targets=["target"],
                    profile=dict(id="lash", attribute="wis", kind="damage", resource_key="wis"),
                ),
                "No visible target can be reached.",
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            t = await s.get(MasterTurn, tid)
            assert t.status == "done", t.trace
            assert t.trace["outcomes"]["source"]["status"] == "denied"
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 24
            assert list(await s.scalars(select(Event))) == []
        assert "SECRET private reasoning" not in json.dumps(provider.prompts[-1])
        await engine.dispose()

    asyncio.run(run())


def test_receipt_recovers_after_commit_before_trace_write(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                dict(
                    kind="ability",
                    reason="Sight",
                    difficulty=1,
                    profile=dict(id="sight", attribute="wis", kind="check", resource_key="wis"),
                ),
                "Vines reveal the path.",
            ]
        )
        service = MasterService(maker, Bus(), provider)
        tid = await service.run_turn("c")
        async with maker() as s:
            t = await s.get(MasterTurn, tid)
            assert t.status == "done", t.trace
            t.status = "failed"
            t.trace = {**t.trace, "outcomes": {}}
            await s.commit()
        # Neither admission nor dice nor narration is regenerated: all were saved.
        assert await MasterService(maker, Bus(), Provider([])).run_turn("c") == tid
        async with maker() as s:
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 21
            assert len(list(await s.scalars(select(Event)))) == 1
            assert len(list(await s.scalars(select(Message).where(Message.kind == "narration")))) == 1
        await engine.dispose()

    asyncio.run(run())


def test_startup_recovery_uses_saved_paid_outcome(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        admission = dict(
            kind="ability",
            reason="Sight",
            difficulty=1,
            profile=dict(id="sight", attribute="wis", kind="check", resource_key="wis"),
        )
        tid = await MasterService(maker, Bus(), Provider([admission, RuntimeError("offline")])).run_turn("c")
        resumed = MasterService(maker, Bus(), Provider(["The saved vines reveal the path."]))

        class QuietPreparer:
            async def run_due(self, *args):
                pass

        resumed.preparer = QuietPreparer()
        await resumed.recover(startup=True)
        async with maker() as s:
            t = await s.get(MasterTurn, tid)
            assert t.status == "done", t.trace
            assert not t.trace.get("rolled_back")
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 21
            assert not list(await s.scalars(select(Message).where(Message.kind == "system")))
        await engine.dispose()

    asyncio.run(run())


def test_automatic_retries_bounded_and_explicit_retry_preserves_receipt(tmp_path):
    from app.core.campaigns import Viewer
    from app.core.chat import retry_message
    from app.db.models import User

    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        admission = dict(
            kind="ability",
            reason="Sight",
            difficulty=1,
            profile=dict(id="sight", attribute="wis", kind="check", resource_key="wis"),
        )
        tid = await MasterService(maker, Bus(), Provider([admission, RuntimeError("offline")])).run_turn("c")
        failing = Provider([RuntimeError("offline"), RuntimeError("offline")])
        service = MasterService(maker, Bus(), failing)

        class QuietPreparer:
            async def run_due(self, *args):
                pass

        service.preparer = QuietPreparer()
        for _ in range(3):
            await service.recover()
        assert len(failing.prompts) == 2
        async with maker() as s:
            t = await s.get(MasterTurn, tid)
            assert t.trace["recovery_attempts"] == 2
            c = await s.get(Campaign, "c")
            viewer = Viewer(await s.get(User, "u"), c, next(x for x in c.seats if x.id == "seat"))
            source = await retry_message(s, viewer, "source")
            assert source.turn_id == tid
            await s.commit()
        assert await MasterService(maker, Bus(), Provider(["Saved outcome narrated."])).run_turn("c") == tid
        async with maker() as s:
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 21
            assert len(list(await s.scalars(select(Event)))) == 1
        await engine.dispose()

    asyncio.run(run())
