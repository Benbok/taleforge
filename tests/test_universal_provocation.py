import asyncio
from types import SimpleNamespace

import pytest

from app.core.universal.combat import run_exchange
from app.core.universal.provocation import provokes
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Message
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2
from tests.test_exploration_resolution import prepare
from tests.test_universal_combat_actions import attack
from tests.test_universal_exchange import enemy
from tests.test_universal_resolution import setup
from tests.test_universal_review_regressions import _down


@pytest.mark.parametrize("kinds", [("speak",), ("observe",), ("wait",), ("hold_breath",), ("speak", "wait")])
@pytest.mark.parametrize("seconds", [6, 60])
def test_quiet_words_and_looking_do_not_provoke(kinds, seconds):
    action = SimpleNamespace(operations=[SimpleNamespace(kind=k) for k in kinds], elapsed_game_seconds=seconds)
    assert not provokes(action)


@pytest.mark.parametrize(
    "kinds,seconds",
    [
        (("move",), 6),
        (("take",), 6),
        (("weapon_attack",), 6),
        (("free_effect",), 6),
        (("speak",), 61),
        (("speak", "take"), 6),
        ((), 6),
    ],
)
def test_anything_else_provokes(kinds, seconds):
    assert provokes(SimpleNamespace(operations=[SimpleNamespace(kind=k) for k in kinds], elapsed_game_seconds=seconds))


@pytest.mark.parametrize("down", [False, True])
def test_a_quiet_exchange_replayed_adds_no_reply(tmp_path, down):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            if down:
                _down(await s.get(Character, "hero"))
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await prepare(s, ctx, "wait", source="mundane")
            results = await run_exchange(ctx, action, request_key="quiet")
            assert len(results) == 1
            replay = await run_exchange(ctx, action, request_key="quiet")
            assert len(replay) == 1 and replay[0].status == "repeated"
            if not down:
                (await s.get(Message, "m")).seq = 0
                await s.flush()
                ctx.dice = FixedDice([15, 1, 15, 1])
                action = await attack(s, ctx, [EffectIntentV2(kind="damage")], targets=["foe"])
                assert len(await run_exchange(ctx, action, request_key="attack")) == 2
        await engine.dispose()

    asyncio.run(run())
