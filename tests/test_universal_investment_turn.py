import asyncio
from types import SimpleNamespace

import pytest

from app.agents.master.investment import decide_investment
from app.core.universal.investment import submit_decision
from app.core.universal.profiles import load_actor
from app.core.universal.resolution import ResolutionContext
from app.db.models import Campaign, GameSession, MasterTurn, Message
from app.rules.dice import FixedDice
from tests.test_exploration_resolution import prepare, run_low
from tests.test_universal_resolution import setup

# hero: wis 14 (+2), level 1: a natural 8 totals 10, misses DC 12 by 2 and costs 6


class Bus:
    def __init__(self):
        self.sent = []

    async def publish(self, campaign_id, envelope, to=None):
        self.sent.append(envelope)


async def world(tmp_path, wis="20", rolls=(8,), **extra):
    engine, maker = await setup(tmp_path)
    await run_low(maker, wis)
    async with maker() as s:
        ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20]))
        compiled = await prepare(s, ctx, "observe", source="mundane", resolution="check")
        s.add(GameSession(id="game", campaign_id="c"))
        s.add(MasterTurn(id="turn", campaign_id="c", session_id="game", upto_seq=1, trace={}))
        (await s.get(Campaign, "c")).last_seq = 1
        await s.commit()
    compiled = compiled.model_copy(update={"difficulty": 12})
    bus = Bus()
    service = SimpleNamespace(
        maker=maker, bus=bus, dice_factory=lambda: FixedDice(list(rolls)), investments={}, **extra
    )
    return engine, maker, service, bus, SimpleNamespace(proposal=compiled, schema_version=2)


async def decide(service, maker, compiled, trace, **extra):
    async with maker() as s:
        sheet, resources = await load_actor(s, "c", "hero")
    campaign = SimpleNamespace(id="c")
    return await decide_investment(
        service, campaign, "game", "turn", trace, compiled, "m", sheet, resources, "seat", **extra
    )


async def open_offer(bus):
    for _ in range(200):
        if bus.sent:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the offer never reached the table")


def test_accepting_the_offer_invests_and_settles_the_card(tmp_path):
    async def run():
        engine, maker, service, bus, compiled = await world(tmp_path)
        trace = {}
        task = asyncio.create_task(decide(service, maker, compiled, trace))
        await open_offer(bus)
        assert submit_decision(service, "c", "m", True)
        assert await task == ((8,), True)
        assert trace["rolls"]["m"] == [8] and trace["investment"]["m"] == "invested"
        async with maker() as s:
            assert (await s.get(Message, "invest_m")).data["status"] == "invested"
        assert len(bus.sent) == 2 and bus.sent[0]["payload"]["id"] == bus.sent[1]["payload"]["id"]
        await engine.dispose()

    asyncio.run(run())


def test_declining_or_silence_keeps_the_roll_as_it_fell(tmp_path):
    async def run():
        engine, maker, service, bus, compiled = await world(tmp_path, investment_timeout=0.05)
        assert await decide(service, maker, compiled, {}) == ((8,), False)
        async with maker() as s:
            assert (await s.get(Message, "invest_m")).data["status"] == "declined"
        await engine.dispose()

    asyncio.run(run())


def test_without_the_energy_there_is_no_pause_and_no_card(tmp_path):
    async def run():
        engine, maker, service, bus, compiled = await world(tmp_path, wis="5")
        assert await decide(service, maker, compiled, {}) == ((8,), False)
        assert bus.sent == []
        async with maker() as s:
            assert await s.get(Message, "invest_m") is None
        await engine.dispose()

    asyncio.run(run())


def test_a_plain_automatic_deed_is_not_prerolled(tmp_path):
    async def run():
        engine, maker, service, bus, compiled = await world(tmp_path)
        automatic = SimpleNamespace(
            proposal=compiled.proposal.model_copy(update={"resolution": "automatic"}), schema_version=2
        )
        assert await decide(service, maker, automatic, {}) == (None, False)
        await engine.dispose()

    asyncio.run(run())


def test_a_saved_decision_is_reused_after_a_restart(tmp_path):
    async def run():
        engine, maker, service, bus, compiled = await world(tmp_path)
        service.dice_factory = lambda: pytest.fail("the saved roll must be reused, never rolled again")
        trace = {"rolls": {"m": [8]}, "investment": {"m": "invested"}}
        assert await decide(service, maker, compiled, trace) == ((8,), True)
        assert bus.sent == []
        await engine.dispose()

    asyncio.run(run())


def test_an_offer_open_at_restart_is_offered_again_once(tmp_path):
    async def run():
        engine, maker, service, bus, compiled = await world(tmp_path, investment_timeout=0.05)
        assert await decide(service, maker, compiled, {}) == ((8,), False)
        async with maker() as s:  # the process died while the card was still open
            card = await s.get(Message, "invest_m")
            card.data = {**card.data, "status": "offered"}
            await s.commit()
        trace = {"rolls": {"m": [8]}, "investment": {"m": "offered"}}
        service.investment_timeout = 1
        task = asyncio.create_task(decide(service, maker, compiled, trace))
        sent = len(bus.sent)
        for _ in range(200):
            if len(bus.sent) > sent:
                break
            await asyncio.sleep(0.01)
        assert submit_decision(service, "c", "m", True)
        assert await task == ((8,), True)
        async with maker() as s:
            assert (await s.get(Message, "invest_m")).data["status"] == "invested"
        await engine.dispose()

    asyncio.run(run())


def test_the_narrator_is_told_when_the_success_was_paid_for():
    from app.agents.master.action_results import public_outcome
    from app.rules.universal.exploration import ExplorationOutcome
    from app.rules.universal.profiles import CheckProof

    def outcome(invested):
        proof = CheckProof(
            target_id="hero", attribute="wis", natural=8, modifier=2, total=12, success=True, invested=invested
        )
        return public_outcome(ExplorationOutcome(success=True, checks=[proof], description="Он слушает."), "r")

    assert outcome(2)["invested"] is True and outcome(0)["invested"] is False


def test_an_ai_player_is_never_asked_so_the_table_does_not_wait(tmp_path):
    async def run():
        engine, maker, service, bus, compiled = await world(tmp_path)
        assert await decide(service, maker, compiled, {}, ask_player=False) == ((8,), False)
        assert bus.sent == []
        async with maker() as s:
            assert await s.get(Message, "invest_m") is None
        await engine.dispose()

    asyncio.run(run())
