# ruff: noqa: F811
"""Модель в фазе структуры (спецификация 2026-10-12, §8): один вызов и одна коррекция, fallback, лимит в БД."""

from datetime import timedelta

from app.agents import layout_model
from app.agents.llm import ScriptedLLM
from app.core.world_generation.service import Orchestrator
from app.db.models import Campaign, LlmCall, WorldGenerationState, now
from app.gateway.coordination import InMemoryCoordination
from tests.game import run
from tests.layout_plan_pilot import model_layout
from tests.test_layout_plan_phase import _plan_root
from tests.test_layout_preparation import _areas, _setup
from tests.test_master import rows
from tests.test_scene_model import _with
from tests.test_world_generation import _fast_retry, _prepare, _row  # noqa: F401 — фикстура

KEYS = ["clue_relic", "npc:npc_warden"]


def _good(messages, tools):
    return {"tool_calls": [(layout_model.TOOL, model_layout(KEYS))]}


def _bad(messages, tools):
    raw = model_layout(KEYS)
    raw["parts"] = [p for p in raw["parts"] if p["part_ref"] != "crypt"]
    return {"tool_calls": [(layout_model.TOOL, raw)]}


def _flags(settings, cid, **flags):
    async def go(s):
        c = await s.get(Campaign, cid)
        c.settings = {**(c.settings or {}), **flags}
        await s.commit()

    run(settings, go)


def _orch(llm):
    return Orchestrator(InMemoryCoordination(), llm=llm)


def _on(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    _flags(settings, cid, location_layouts_llm=True)
    return cid


def test_model_layout_is_used_and_counted(client, admin, settings):
    cid = _on(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    llm = ScriptedLLM([_good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready"
    row = _row(settings, ref)
    assert row.quality == "normal" and row.llm_attempt_count == 1 and row.result_manifest["notes"] == []
    assert set(_areas(settings, root)) == {"road", "brook", "narthex", "nave", "chapel", "sacristy", "vault", "crypt"}
    (call,) = rows(settings, LlmCall, LlmCall.generation_id == ref)
    assert call.purpose == layout_model.PURPOSE and call.error is None


def test_one_correction_then_deterministic_fallback(client, admin, settings):
    cid = _on(client, admin, settings)
    _root, ref = _plan_root(settings, cid)
    llm = ScriptedLLM([_bad, _good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready"
    assert _row(settings, ref).llm_attempt_count == 2 and _row(settings, ref).quality == "normal"
    assert "Сервер не принял план" in llm.requests[1]["messages"][-1]["content"]

    cid2 = cid
    root2, ref2 = _plan_root(settings, cid2)
    llm = ScriptedLLM([_bad, _bad, _good])
    assert _prepare(settings, cid2, ref2, _orch(llm)) == "ready"
    row = _row(settings, ref2)
    assert row.quality == "fallback" and row.llm_attempt_count == 2 and len(llm.requests) == 2
    assert "fallback:invalid_proposal" in row.result_manifest["notes"]
    assert set(_areas(settings, root2)) == {"road", "narthex", "nave", "chapel", "crypt", "vault"}
    assert len(rows(settings, LlmCall, LlmCall.generation_id == ref2)) == 2


def test_limit_survives_restart_retry_and_reentry(client, admin, settings):
    cid = _on(client, admin, settings)
    _root, ref = _plan_root(settings, cid)

    async def spent(s):
        (await s.get(WorldGenerationState, ref)).llm_attempt_count = 2
        await s.commit()

    run(settings, spent)
    llm = ScriptedLLM([_good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready"
    assert llm.requests == [] and "fallback:llm_limit" in _row(settings, ref).result_manifest["notes"]
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready" and llm.requests == []  # готово: ни одного вызова


def test_flag_off_spend_limit_and_model_down(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    _flags(settings, cid, location_layouts_llm=False)
    _root, ref = _plan_root(settings, cid)
    llm = ScriptedLLM([_good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready" and llm.requests == []
    assert _row(settings, ref).quality == "normal"  # модель выключена: детерминированный путь — обычный

    _flags(settings, cid, location_layouts_llm=True, spend_limit_usd=0.0)
    _root2, ref2 = _plan_root(settings, cid)
    assert _prepare(settings, cid, ref2, _orch(llm)) == "ready" and llm.requests == []
    assert "fallback:spend_limit" in _row(settings, ref2).result_manifest["notes"]

    _flags(settings, cid, spend_limit_usd=None)
    _root3, ref3 = _plan_root(settings, cid)
    down = ScriptedLLM([])
    assert _prepare(settings, cid, ref3, _orch(down)) == "ready"
    row = _row(settings, ref3)
    assert row.llm_attempt_count == 1 and "fallback:llm_failed" in row.result_manifest["notes"]


def test_context_over_budget_skips_model(client, admin, settings, monkeypatch):
    cid = _on(client, admin, settings)
    _root, ref = _plan_root(settings, cid)
    monkeypatch.setattr(layout_model, "MAX_IN", 50)
    llm = ScriptedLLM([_good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready" and llm.requests == []
    row = _row(settings, ref)
    assert row.llm_attempt_count == 0 and "fallback:context_budget" in row.result_manifest["notes"]


def test_correction_over_budget_uses_fallback_without_spending_second_call(client, admin, settings):
    cid = _on(client, admin, settings)
    _root, ref = _plan_root(settings, cid)
    llm = ScriptedLLM([{"text": "x" * 25000}, _good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready"
    row = _row(settings, ref)
    assert row.quality == "fallback" and row.llm_attempt_count == 1
    assert "fallback:context_budget" in row.result_manifest["notes"]
    assert len(llm.requests) == 1
    (call,) = rows(settings, LlmCall, LlmCall.generation_id == ref)
    assert call.error is not None


def test_late_answer_after_lost_lease_is_dropped(client, admin, settings):
    cid = _on(client, admin, settings)
    root, ref = _plan_root(settings, cid)

    def slow(messages, tools):
        async def expire(s):
            row = await s.get(WorldGenerationState, ref)
            row.lease_until = now() - timedelta(seconds=1)
            row.lease_token = "чужой"
            row.revision += 1
            await s.commit()

        import asyncio
        import threading

        done = threading.Event()
        threading.Thread(target=lambda: (asyncio.run(_with(settings, expire)), done.set())).start()
        done.wait()
        return _good(messages, tools)

    assert _prepare(settings, cid, ref, _orch(ScriptedLLM([slow]))) == "lost"
    assert _areas(settings, root) == {}


def test_host_intent_never_calls_model(client, admin, settings):
    from tests.test_layout_preparation import _complex

    cid = _on(client, admin, settings)
    _village, _temple, ref = _complex(settings, cid)
    llm = ScriptedLLM([_good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready" and llm.requests == []
