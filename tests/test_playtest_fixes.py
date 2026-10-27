"""Фиксы после игровой сессии 2026-10-04: заклинания в таблице сцены, криты с последствием в листе героя,
враги на схеме боя."""

from tests.game import import_base, party
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры хода
from tests.test_tools import call, play


def test_crit_success_note_and_no_nudge(client, admin, settings):
    import_base(settings)
    c, _, ch = party(client, admin)
    args = {"character_id": ch["id"], "stat": "athletics", "difficulty": "dc.nearly_impossible", "reason": "x"}

    async def fn(ctx):
        from app.agents.master.helpers import _unsettled_fails

        r = await call(ctx, "roll_check", args)
        return r, _unsettled_fails(ctx, [{"tool": "roll_check", "args": args, "result": r}])

    r, fails = play(settings, c["id"], [20], fn)
    assert r["result"]["critical"] == "success" and "близко к задуманному" in r["result"]["critical_note"]
    assert fails == []
