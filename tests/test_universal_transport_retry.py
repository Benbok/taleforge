import asyncio
from types import SimpleNamespace

from app.agents.master.service import MasterService
from app.core.universal.profiles import load_actor
from app.db.models import MasterTurn, User
from app.gateway.ws import _retry
from app.rules.dice import FixedDice
from tests.test_universal_master import Bus, Provider, prepare, seed_legacy
from tests.test_universal_resolution import setup


def test_websocket_retry_dispatches_original_turn_without_pending_source(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        proposal = dict(
            kind="ability",
            reason="Sight",
            difficulty=1,
            profile=dict(id="sight", attribute="wis", kind="check", resource_key="wis"),
        )
        await seed_legacy(maker, proposal)
        service = MasterService(
            maker, Bus(), Provider([RuntimeError("narrator failed")]), dice_factory=lambda: FixedDice([10])
        )
        tid = await service.run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            turn.trace = {**turn.trace, "recovery_attempts": 2}
            user = await s.get(User, "u")
            await s.commit()
        service.llm = Provider(["The vines reveal a path."])
        dispatched = []

        def reject_notify(cid):
            raise AssertionError("A retained receipt is not a pending source")

        proxy = SimpleNamespace(_spawn=dispatched.append, run_turn=service.run_turn, notify=reject_notify)
        app = SimpleNamespace(state=SimpleNamespace(sessionmaker=maker, bus=Bus(), master=proxy))
        connection = SimpleNamespace(campaign_id="c", seat_id="seat")
        await _retry(app, user, connection, {"message_id": "source"})
        assert len(dispatched) == 1
        assert await dispatched[0] == tid
        async with maker() as s:
            assert (await s.get(MasterTurn, tid)).status == "done"
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 21
        await engine.dispose()

    asyncio.run(run())
