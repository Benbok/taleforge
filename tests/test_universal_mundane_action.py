import asyncio

from sqlalchemy import select

from app.agents.master.service import MasterService
from app.core.universal.profiles import load_actor
from app.db.models import Event, HeroAbility, MasterTurn, Message
from app.rules.dice import FixedDice
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup


def test_saved_torch_check_resumes_without_magic_energy_or_replanning(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        admission = dict(
            kind="ability",
            reason="Разжечь факел проверкой ловкости",
            public_reason="Вы пытаетесь высечь искру камнем.",
            attribute="dex",
            difficulty=10,
            targets=[],
            profile=dict(id="craft_torch", kind="check", attribute="dex", resource_key=None, effects=[]),
        )
        async with maker() as s:
            turn = MasterTurn(
                id="torch-turn",
                campaign_id="c",
                session_id="game",
                upto_seq=1,
                status="failed",
                trace=dict(universal=True, sources=["source"], admissions={"source": admission}, outcomes={}, scene={}),
            )
            s.add(turn)
            await s.flush()
            (await s.get(Message, "source")).turn_id = turn.id
            await s.commit()
        provider = Provider(["Факел загорелся."])
        service = MasterService(maker, Bus(), provider, dice_factory=lambda: FixedDice([14]))
        assert await service.run_turn("c") == "torch-turn"
        async with maker() as s:
            turn = await s.get(MasterTurn, "torch-turn")
            assert turn.status == "done", turn.trace.get("error")
            result = turn.trace["outcomes"]["source"]
            assert result["success"] and result["cost"] == "0"
            assert (await load_actor(s, "c", "hero"))[1].energies["dex"] == 20
            assert not list(await s.scalars(select(HeroAbility)))
            assert len(list(await s.scalars(select(Event)))) == 1
        assert len(provider.prompts) == 1  # Narrate the saved decision; no new admission call.
        assert await service.run_turn("c") is None
        await engine.dispose()

    asyncio.run(run())
