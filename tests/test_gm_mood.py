"""Эмоции мастера в игре (app/emotion/game.py), черновик повествования по кускам и цена потокового ответа."""

import asyncio
from types import SimpleNamespace

from app.agents.llm import _collect_stream
from app.emotion import game as mood
from app.emotion.analyzers import LLMAnalyzer
from app.emotion.schemas import EmotionState
from tests.test_master import DONE, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры


def test_step_decays_then_adds_and_clamps():
    p = mood.persona_of("tired_mentor")
    s = mood.step(EmotionState(anger=4.0, joy=0.2), p, EmotionState(anger=9.0))
    assert s.anger == 10.0 and s.joy == 0.0  # затухание раньше дельты, потолок 10
    assert mood.persona_of("нет такого").name == p.name


def test_hero_naturals_counts_only_heroes():
    events = [
        SimpleNamespace(actor_id="ch_1", payload={"result": {"natural": 20}}),
        SimpleNamespace(actor_id="ch_1", payload={"rolls": [{"natural": 1}, {"natural": 7}]}),
        SimpleNamespace(actor_id="en_goblin", payload={"natural": 20}),
    ]
    assert mood.hero_naturals(events, {"ch_1"}) == (1, 1)
    delta = mood.crit_delta(mood.persona_of("tired_mentor"), 1, 0)
    assert delta.joy == 1.5


def test_llm_analyzer_parse_is_forgiving():
    assert LLMAnalyzer.parse('```json\n{"joy": 9, "anger": "x"}\n```') == EmotionState(joy=4.0)
    assert LLMAnalyzer.parse("не JSON") == EmotionState()


def test_stream_reply_keeps_tokens_and_cost():
    def chunk(text):
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])

    async def resp():
        for t in ("Туман ", "густеет."):
            yield chunk(t)

    full = SimpleNamespace(
        model="gemini/gemini-2.5-flash", usage=SimpleNamespace(prompt_tokens=120, completion_tokens=8)
    )
    fake = SimpleNamespace(
        stream_chunk_builder=lambda raw, messages: full, completion_cost=lambda completion_response: 0.0021
    )
    got: list[str] = []

    async def push(t):
        got.append(t)

    reply = asyncio.run(_collect_stream(fake, resp(), "gemini/x", [], push, 0.0))
    assert got == ["Туман ", "густеет."] and reply.text == "Туман густеет."
    assert (reply.tokens_in, reply.tokens_out, reply.cost) == (120, 8, 0.0021)  # раньше поток писал 0 в расходы
