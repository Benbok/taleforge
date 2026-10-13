"""Small checks for findings added after the first playtest fixes."""

import asyncio
import sys
from types import SimpleNamespace

import pytest

from app.agents.llm import LiteLLMClient, LLMQuotaError, quota_error
from app.core import combat
from tests.test_tools import call, game, play  # noqa: F401


def test_charmed_enemy_cannot_attack_source(game):  # noqa: F811 — imported fixture
    settings, cid, hero = game

    async def scenario(ctx):
        spawned = await call(
            ctx,
            "spawn_entity",
            {
                "creature_template_id": "creature.goblin",
                "name": "Стражник",
                "zone": "melee",
            },
        )
        enemy = spawned["result"]["spawned"][0]["id"]
        effect = await call(
            ctx,
            "apply_effect",
            {
                "target_id": enemy,
                "effect_template_id": "condition.charmed",
                "source": hero,
                "reason": "очарование стражника",
            },
        )
        assert effect["ok"], effect
        result = await call(ctx, "resolve_attack", {"attacker_id": enemy, "target_id": hero, "attack": "scimitar"})
        assert not result["ok"] and "очарован" in result["error"]
        assert combat._pick_target(ctx, ctx.world.actor(enemy)) is None
        notes = []
        await combat.creature_turn(ctx, ctx.world.actor(enemy), "test:charmed", notes, None)
        assert any("очарован" in note for note in notes)

    play(settings, cid, [], scenario)


def test_provider_budget_blocks_followup_network_calls(monkeypatch):
    calls = []

    async def completion(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("429 RESOURCE_EXHAUSTED: exceeded its monthly spending cap")

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=completion))
    client = LiteLLMClient()

    async def scenario():
        for model in ("gemini/main", "gemini/technical"):
            with pytest.raises(LLMQuotaError) as caught:
                await client.complete([], model=model)
            assert caught.value.budget_exhausted

    asyncio.run(scenario())
    assert len(calls) == 1
    assert quota_error("429 temporary quota exceeded").budget_exhausted is False
    assert quota_error("ordinary timeout") is None
