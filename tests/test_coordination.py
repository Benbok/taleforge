"""Согласование внутри сервера (app/gateway/coordination.py): замки кампаний и кнопки реакций."""

import asyncio

import pytest

from app.gateway.coordination import InMemoryCoordination


def test_locks_are_per_campaign_and_kind():
    c = InMemoryCoordination()
    assert c.turn_lock("c1") is c.turn_lock("c1")
    assert c.turn_lock("c1") is not c.turn_lock("c2")
    assert c.turn_lock("c1") is not c.intro_lock("c1") is not c.whisper_lock("c1")


def test_prompt_waits_for_the_answer_of_its_own_seat():
    async def go():
        c = InMemoryCoordination()
        fut = c.open_prompt("rx1", "c1", "s1")
        payload = {"prompt_id": "rx1", "trigger": "«Волк» выходит из ближнего боя"}
        c.describe_prompt("rx1", payload)

        assert c.pending_prompt("c1", "s1") == payload  # переподключение: кнопка ещё открыта
        assert c.pending_prompt("c1", "s2") is None  # чужая кнопка не видна
        assert c.answer_prompt("rx1", "s2", "opportunity_attack") is False  # и чужой ответ не принимается
        assert c.answer_prompt("rx1", "s1", "opportunity_attack") is True
        assert await fut == "opportunity_attack"
        assert c.answer_prompt("rx1", "s1", "skip") is False  # ответ уже принят
        c.close_prompt("rx1")
        assert c.pending_prompt("c1", "s1") is None
        assert c.answer_prompt("rx1", "s1", "skip") is False  # кнопки больше нет

    asyncio.run(go())


def test_prompt_without_answer_stays_pending():
    async def go():
        c = InMemoryCoordination()
        fut = c.open_prompt("rx1", "c1", "s1")
        c.describe_prompt("rx1", {"prompt_id": "rx1"})
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(fut, timeout=0.01)
        c.close_prompt("rx1")

    asyncio.run(go())
