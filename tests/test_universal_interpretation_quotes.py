import asyncio
import json

from sqlalchemy import select

from app.agents.master.service import MasterService
from app.core.universal.interpretation import normalize_quote
from app.db.models import HeroAbility, MasterTurn
from tests.test_exploration_master import proposal
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup


def quoted(quote):
    return dict(
        proposal(),
        requirements=[{"id": "req_1", "quote": quote, "effect": "cosmetic"}],
        effects=[{"kind": "cosmetic", "required_by": ["req_1"]}],
    )


def test_normalize_quote_folds_case_yo_quotes_and_spaces():
    assert normalize_quote("  Зажигаю «Ёлку»\n") == 'зажигаю "елку"'


def test_a_quote_differing_only_in_case_reaches_the_roll(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)  # the player's words are "Invent a vine sight"
        provider = Provider(
            [
                quoted("INVENT A VINE SIGHT"),
                {"verdict": "pass", "covered_requirements": ["req_1"]},
                "Искры мягко мерцают над ладонью.",
                {"verdict": "pass"},
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            assert (await s.get(MasterTurn, tid)).status == "done"
            assert len(list(await s.scalars(select(HeroAbility)))) == 1
        await engine.dispose()

    asyncio.run(run())


def test_a_quote_with_other_words_is_still_rejected(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                quoted("summon a dragon"),
                {"verdict": "pass", "covered_requirements": ["req_1"]},
                quoted("summon a dragon"),
                {"verdict": "pass", "covered_requirements": ["req_1"]},
            ]
        )
        await MasterService(maker, Bus(), provider).run_turn("c")
        assert "дословным фрагментом" in json.dumps(provider.prompts[2], ensure_ascii=False)
        await engine.dispose()

    asyncio.run(run())
