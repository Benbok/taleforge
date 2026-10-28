"""Последствия поступков и случайности мира: отношение NPC и фракций, их ответ, вдохновение, встречи и находки."""

from app.core import standing as sd
from app.db.models import Campaign
from app.tools.registry import execute
from app.tools.runtime import flush_outbox, open_context
from tests.game import (
    QueueDice,
    run,
    worlds,  # noqa: F401 — фикстура
)


def play(settings, cid, dice, fn):
    async def go(s):
        ctx = await open_context(s, await s.get(Campaign, cid), QueueDice(dice), turn_id="t_test", seat_id=None)
        out = await fn(ctx)
        await flush_outbox(s, ctx)
        await s.commit()
        return out

    return run(settings, go)


def test_tiers_follow_points():
    assert [sd.tier_of(p) for p in (0, 1, 2, 4, 5, 9, 10, 15)] == [0, 0, 1, 1, 2, 2, 3, 3]
    assert [sd.tier_of(p) for p in (-1, -2, -5, -10)] == [0, -1, -2, -3]


def _at_old_mother(ctx):
    return execute(
        ctx,
        "create_location",
        {"name": "Старая Мать", "template_id": "location.old_mother", "make_current": True},
    )
