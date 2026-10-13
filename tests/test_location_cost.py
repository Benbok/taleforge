# ruff: noqa: F811
"""Сводка расходов подготовки места (спецификация 2026-10-12, §8, §10): все фазы, исправления и рассуждения."""

from app.agents import layout_model
from app.agents.llm import LLMReply, ScriptedLLM, ToolCall
from app.core import preparation
from app.core.world_generation.service import Orchestrator
from app.gateway.coordination import InMemoryCoordination
from app.tools.registry import execute
from tests.game import run
from tests.layout_plan_pilot import model_layout
from tests.test_layout_model_phase import _bad, _on
from tests.test_layout_plan_phase import _plan_root
from tests.test_map import _play
from tests.test_world_generation import _fast_retry, _prepare  # noqa: F401 — фикстура

KEYS = ["clue_relic", "npc:npc_warden"]


def _priced(messages, tools):
    return LLMReply(
        text="",
        tool_calls=[ToolCall("c", layout_model.TOOL, model_layout(KEYS))],
        model="tech",
        tokens_in=1200,
        tokens_out=800,
        reasoning_tokens=300,
        cost=0.004,
        latency_ms=50,
    )


def test_cost_sums_structure_corrections_and_reasoning(client, admin, settings):
    cid = _on(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    assert (
        _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=ScriptedLLM([_bad, _priced]))) == "ready"
    )
    cost = run(settings, lambda s: preparation.location_cost(s, cid, root))
    layout = cost["phases"]["location_layout"]
    assert layout["calls"] == 2 and layout["errors"] == 1 and layout["tokens_reasoning"] == 300
    assert layout["tokens_in"] == 1210 and layout["ready"] == 1 and layout["duration_ms"] >= 0
    assert cost["phases"]["location_geometry"]["rows"] == 8 and cost["phases"]["location_geometry"]["calls"] == 0
    assert cost["total"]["calls"] == 2 and round(cost["total"]["cost"], 6) == 0.004


def test_reentry_adds_no_structure_calls(client, admin, settings):
    cid = _on(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=ScriptedLLM([_priced])))
    before = run(settings, lambda s: preparation.location_cost(s, cid, root))["phases"]["location_layout"]["calls"]
    _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=ScriptedLLM([_priced])))
    after = run(settings, lambda s: preparation.location_cost(s, cid, root))["phases"]["location_layout"]["calls"]
    assert before == after == 1


def test_host_tool_reads_without_writing(client, admin, settings):
    cid = _on(client, admin, settings)
    root, _ref = _plan_root(settings, cid)
    out = _play(settings, cid, lambda ctx: execute(ctx, "preparation_cost", {"location_id": root}))
    assert out["ok"] and out["result"]["root_id"] == root
