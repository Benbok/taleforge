"""Когда замысел мастера не удалось воплотить или проза не прошла проверку, игрок всё равно получает рассказ."""

import asyncio
import json

from app.agents.master.exploration import reviewed_narration


def run_narration(replies):
    calls = []

    async def ask(purpose, messages):
        calls.append(purpose)
        return replies[purpose].pop(0)

    async def go():
        from types import SimpleNamespace

        async def noop(*a, **k):
            return None

        service = SimpleNamespace(maker=None)
        import app.agents.master.exploration as ex

        original = ex.store
        ex.store = noop
        try:
            return await reviewed_narration(
                service, None, "t1", {}, {"m": {"description": "Попытка удалась."}}, {}, [], ask
            )
        finally:
            ex.store = original

    return asyncio.run(go()), calls


def verdict(kind):
    return json.dumps({"verdict": kind, "message": "не так"}, ensure_ascii=False)


def test_two_failed_reviews_still_give_a_story_not_the_plain_outcome():
    text, calls = run_narration(
        {
            "narrate": ["Первая.", "Вторая.", "Лошадь косится на морковку и тянется к ладони."],
            "narration_review": [verdict("mismatch"), verdict("mismatch")],
        }
    )
    assert text == "Лошадь косится на морковку и тянется к ладони."
    assert calls == ["narrate", "narration_review", "narrate", "narration_review", "narrate"]
