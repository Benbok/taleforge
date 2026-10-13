"""Техническая модель структуры комплекса (спецификация 2026-10-12, §3.2, §8): схема, бюджет, разбор, коррекция."""

import asyncio
import json

import pytest

from app.agents import layout_model
from app.agents.llm import LLMError, LLMReply, ScriptedLLM, ToolCall
from app.core.layout.contracts import LayoutError
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.world_generation.contracts import Blocked
from tests.layout_plan_pilot import model_layout, temple_mandate, temple_plan

KEYS = ["clue_relic", "npc:npc_warden"]


def _check(intent):
    DeterministicLayoutProvider().propose(intent, seed=7, root_id="root")


def _ask(llm, msgs=None):
    return asyncio.run(
        layout_model.ask(
            llm,
            temple_mandate(),
            model="m",
            api_base=None,
            msgs=msgs if msgs is not None else [],
            check=_check,
        )
    )


def test_schema_is_strict_and_lists_holders():
    fn = layout_model.spec(temple_mandate())["function"]
    assert fn["name"] == layout_model.TOOL
    params = fn["parameters"]
    part = params["properties"]["parts"]["items"]
    assert params["additionalProperties"] is False and part["additionalProperties"] is False
    assert part["properties"]["anchors"]["items"]["enum"] == KEYS
    assert "outside_id" not in params["properties"]["approaches"]["items"]["properties"]
    assert set(part["properties"]["shape"]["enum"]) == {"rect", "circle", "l_shape", "corridor", "open", "cave"}


def test_brief_carries_no_plot_secrets():
    plan = temple_plan()
    port = plan["locations"][0]
    warden = next(n for n in plan["npcs"] if n["id"] == "npc_warden")
    text = (
        layout_model.SYSTEM
        + (layout_model.brief(temple_mandate()) or "")
        + json.dumps(layout_model.spec(temple_mandate()), ensure_ascii=False)
    )
    for secret in (port["secret"], warden["secret"], warden["fear"], "Журнал смотрителя подчищен", "Мать Ирса"):
        assert secret not in text
    assert "Тайник" in text and "secret" in text and "clue_relic" in text


def test_brief_trims_optional_context_but_not_obligations(monkeypatch):
    m = temple_mandate()
    full = layout_model.brief(m)
    assert full is not None
    budget = layout_model.input_estimate(
        m, [{"role": "system", "content": layout_model.SYSTEM}, {"role": "user", "content": full}]
    )
    monkeypatch.setattr(layout_model, "MAX_IN", budget - 5)
    trimmed = layout_model.brief(m)
    assert trimmed is not None and m.mood not in trimmed and "clue_relic" in trimmed and "Крипта" in trimmed
    monkeypatch.setattr(layout_model, "MAX_IN", 50)
    assert layout_model.brief(m) is None


def test_valid_answer_becomes_intent_with_tokens():
    reply = LLMReply(
        text="",
        tool_calls=[ToolCall("c1", layout_model.TOOL, model_layout(KEYS))],
        model="tech",
        tokens_in=900,
        tokens_out=700,
        reasoning_tokens=300,
        cost=0.002,
        latency_ms=40,
    )
    intent, attempt, retry = _ask(ScriptedLLM([reply]))
    assert intent is not None and retry is None and attempt.error is None
    assert intent.entry == "road" and all(a.outside_id is None for a in intent.approaches)
    assert (attempt.tokens_in, attempt.tokens_out, attempt.tokens_reasoning) == (900, 700, 300)


@pytest.mark.parametrize(
    "mutate, text",
    [
        (lambda r: r["parts"].pop(), "нет обязательной части crypt"),
        (lambda r: r.update(colour="red"), "только"),
        (lambda r: r["approaches"][0].update(outside_id="en_x"), "outside_id"),
        (
            lambda r: next(p for p in r["parts"] if p["part_ref"] == "vault").update(secret=False, required=True),
            "vault",
        ),
    ],
)
def test_invalid_answer_returns_correction(mutate, text):
    raw = model_layout(KEYS)
    mutate(raw)
    msgs: list = []
    intent, attempt, retry = _ask(ScriptedLLM([{"tool_calls": [(layout_model.TOOL, raw)]}]), msgs)
    assert intent is None and retry and text in retry and attempt.error
    assert "Сервер не принял план" in msgs[-1]["content"]


def test_layout_errors_from_provider_are_corrections():
    def bad(intent):
        raise LayoutError(["часть «nave» не помещается рядом с «narthex»"])

    raw = model_layout(KEYS)
    intent, attempt, retry = asyncio.run(
        layout_model.ask(
            ScriptedLLM([{"tool_calls": [(layout_model.TOOL, raw)]}]),
            temple_mandate(),
            model="m",
            api_base=None,
            msgs=[],
            check=bad,
        )
    )
    assert intent is None and "не помещается" in retry


def test_model_failure_is_not_corrected():
    class Down:
        async def complete(self, *a, **kw):
            raise LLMError("сеть")

    intent, attempt, retry = _ask(Down())
    assert intent is None and retry is None and "сеть" in attempt.error


def test_request_respects_output_budget():
    llm = ScriptedLLM([{"tool_calls": [(layout_model.TOOL, model_layout(KEYS))]}])
    seen = {}
    orig = llm.complete

    async def spy(messages, **kw):
        seen.update(kw)
        return await orig(messages, **kw)

    llm.complete = spy
    _ask(llm)
    assert seen["max_tokens"] == layout_model.MAX_OUT == 3000 and seen["tool_choice"] == "required"


def test_correction_over_context_budget_does_not_call_model():
    llm = ScriptedLLM([{"text": "x" * 25000}, {"tool_calls": [(layout_model.TOOL, model_layout(KEYS))]}])
    msgs: list = []
    assert _ask(llm, msgs)[0] is None
    with pytest.raises(Blocked) as error:
        _ask(llm, msgs)
    assert error.value.reason == "context_budget"
    assert len(llm.requests) == 1


def test_correction_within_context_budget_still_accepts_plan():
    llm = ScriptedLLM([{"text": "неверный ответ"}, {"tool_calls": [(layout_model.TOOL, model_layout(KEYS))]}])
    msgs: list = []
    assert _ask(llm, msgs)[0] is None
    intent, attempt, retry = _ask(llm, msgs)
    assert intent is not None and attempt.error is None and retry is None
    assert len(llm.requests) == 2
