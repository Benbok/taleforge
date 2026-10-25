"""Regressions identified during action boundary architecture review."""

import asyncio

import pytest
from sqlalchemy import select

from app.core.universal.action_intents import ActionIntent
from app.core.universal.contracts import ResolutionContext
from app.core.universal.preparation import prepare_action
from app.core.universal.resolution import resolve_action
from app.db.models import HeroAbility, MasterTurn, Message
from app.rules.dice import FixedDice
from app.rules.universal.failures import ActionValidationError
from tests.test_universal_resolution import setup


@pytest.mark.parametrize(
    "requested",
    [
        {"duration": 3, "clock": "turn"},
        {"target_scope": "scene"},
        {"extra_effects": [{"kind": "heal"}]},
    ],
)
def test_known_profile_cannot_silently_discard_requested_semantics(tmp_path, requested):
    async def run():
        engine, maker = await setup(tmp_path)
        try:
            async with maker() as s:
                ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20]))
                first = await prepare_action(
                    ctx, ActionIntent(kind="ability", attribute="wis", effect="check"), "learn"
                )
                await resolve_action(ctx, first.proposal, "learn")
                await s.commit()
                known = await s.scalar(select(HeroAbility))
                intent = ActionIntent(kind="ability", known_profile_id=known.profile_ref, **requested)
                with pytest.raises(ActionValidationError):
                    await prepare_action(ctx, intent, "changed")
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_provider_failure_remains_technical_after_restart_budget_exhaustion(tmp_path):
    from app.agents.master.service import MasterService
    from tests.test_universal_master import Bus, Provider, prepare

    async def run():
        engine, maker = await setup(tmp_path)
        try:
            await prepare(maker)
            provider = Provider([RuntimeError("offline"), RuntimeError("offline")])
            tid = await MasterService(maker, Bus(), provider).run_turn("c")
            # Independent service instances model restart; no more than two attempts.
            for _ in range(2):
                async with maker() as s:
                    turn = await s.get(MasterTurn, tid)
                    if turn.status == "done":
                        break
                await MasterService(maker, Bus(), provider).run_turn("c")
            async with maker() as s:
                turn = await s.get(MasterTurn, tid)
                source = await s.get(Message, "source")
                assert turn.status == "done"
                assert turn.trace["proposal_attempts"]["source"] <= 2
                assert source.data["action_failure"]["category"] == "internal_error"
            assert len(provider.prompts) <= 2
        finally:
            await engine.dispose()

    asyncio.run(run())
