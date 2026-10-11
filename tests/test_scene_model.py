"""Техническая модель подготовки, поставка 5 (docs/world-objects-delivery5.md, §3): строгие предложения, одна
корректирующая попытка, лимит вызовов фазы в БД, fallback и защита от ответа после потери lease."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.agents import world_generator
from app.agents.llm import ScriptedLLM
from app.core.world_generation import storage
from app.core.world_generation.service import Orchestrator
from app.db.models import Campaign, LlmCall, WorldGenerationState, now
from app.gateway.coordination import InMemoryCoordination
from tests.game import import_base, party, quiet, run
from tests.test_master import rows
from tests.test_world_generation import _generated, _prepare, _room, _row


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    monkeypatch.setattr(storage, "RETRY_AFTER", timedelta(0))


def _campaign(client, admin, settings, *, llm_on=True):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    quiet(client)
    cid = campaign["id"]

    async def flag(s):
        c = await s.get(Campaign, cid)
        c.settings = {**(c.settings or {}), "scene_generation_llm": llm_on}
        await s.commit()

    run(settings, flag)
    return cid


def _slots(tools) -> list[str]:
    return tools[0]["function"]["parameters"]["properties"]["objects"]["items"]["properties"]["slot_ref"]["enum"]


def _named(messages, tools):
    objects = [
        {"slot_ref": ref, "name": f"Модельный {ref}", "description": "Пыльный и старый."}
        for ref in _slots(tools)
        if not ref.startswith("anchor:")
    ]
    return {"tool_calls": [(world_generator.TOOL, {"objects": objects})]}


def _bad(messages, tools):
    return {
        "tool_calls": [(world_generator.TOOL, {"objects": [{"slot_ref": "item:99", "name": "x", "description": ""}]})]
    }


def test_model_names_slots_and_counts_calls(client, admin, settings):
    cid = _campaign(client, admin, settings)
    _room_id, ref = _room(settings, cid)
    llm = ScriptedLLM([_named])
    assert _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=llm)) == "ready"
    row = _row(settings, ref)
    assert row.quality == "normal" and row.llm_attempt_count == 1
    made = _generated(settings, ref)
    assert made and all(e.name.startswith("Модельный ") for e in made)
    spec = llm.requests[0]["tools"][0]["function"]["parameters"]
    assert spec["additionalProperties"] is False  # строгая схема: ни шаблонов, ни чисел, ни id
    assert set(spec["properties"]["objects"]["items"]["properties"]) == {"slot_ref", "name", "description"}
    (call,) = rows(settings, LlmCall, LlmCall.purpose == world_generator.PURPOSE)
    assert call.error is None


def test_invalid_answer_gets_one_correction_then_fallback(client, admin, settings):
    cid = _campaign(client, admin, settings)
    _room_id, ref = _room(settings, cid)
    llm = ScriptedLLM([_bad, _named])
    assert _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=llm)) == "ready"
    assert _row(settings, ref).llm_attempt_count == 2 and _row(settings, ref).quality == "normal"
    assert "Сервер не принял сцену" in llm.requests[1]["messages"][-1]["content"]

    _other, ref2 = _room(settings, cid, name="Погреб")
    llm = ScriptedLLM([_bad, _bad, _named])
    assert _prepare(settings, cid, ref2, Orchestrator(InMemoryCoordination(), llm=llm)) == "ready"
    row = _row(settings, ref2)
    assert row.quality == "fallback" and row.llm_attempt_count == 2 and len(llm.requests) == 2
    assert "fallback:invalid_proposal" in row.result_manifest["notes"]
    assert not any(e.name.startswith("Модельный ") for e in _generated(settings, ref2))


def test_call_limit_survives_restart_and_model_errors_fall_back(client, admin, settings):
    cid = _campaign(client, admin, settings)
    _room_id, ref = _room(settings, cid)

    async def spent(s):
        (await s.get(WorldGenerationState, ref)).llm_attempt_count = 2  # вызовы до рестарта уже потрачены
        await s.commit()

    run(settings, spent)
    llm = ScriptedLLM([_named])
    assert _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=llm)) == "ready"
    assert llm.requests == [] and _row(settings, ref).quality == "fallback"
    assert "fallback:llm_limit" in _row(settings, ref).result_manifest["notes"]

    _other, ref2 = _room(settings, cid, name="Чердак")
    llm = ScriptedLLM([])  # модель недоступна
    assert _prepare(settings, cid, ref2, Orchestrator(InMemoryCoordination(), llm=llm)) == "ready"
    row = _row(settings, ref2)
    assert row.quality == "fallback" and row.llm_attempt_count == 1  # ошибка сети не корректируется


def test_model_off_by_default_and_late_answer_is_dropped(client, admin, settings):
    cid = _campaign(client, admin, settings, llm_on=False)
    _room_id, ref = _room(settings, cid)
    llm = ScriptedLLM([_named])
    assert _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=llm)) == "ready"
    assert llm.requests == [] and _row(settings, ref).llm_attempt_count == 0

    cid2 = cid

    async def on(s):
        c = await s.get(Campaign, cid2)
        c.settings = {**(c.settings or {}), "scene_generation_llm": True}
        await s.commit()

    run(settings, on)
    _other, ref2 = _room(settings, cid, name="Сарай")

    def slow(messages, tools):
        async def expire(s):  # пока модель думала, lease истёк и фазу перехватили
            row = await s.get(WorldGenerationState, ref2)
            row.lease_until = now() - timedelta(seconds=1)
            row.lease_token = "чужой"
            row.revision += 1
            await s.commit()

        import asyncio
        import threading

        done = threading.Event()
        threading.Thread(target=lambda: (asyncio.run(_with(settings, expire)), done.set())).start()
        done.wait()
        return _named(messages, tools)

    llm = ScriptedLLM([slow])
    assert _prepare(settings, cid, ref2, Orchestrator(InMemoryCoordination(), llm=llm)) == "lost"
    assert _generated(settings, ref2) == []  # опоздавший ответ ничего не записал


async def _with(settings, fn):
    from app.db.session import make_engine, make_sessionmaker

    engine = make_engine(settings.database_url)
    try:
        async with make_sessionmaker(engine)() as s:
            return await fn(s)
    finally:
        await engine.dispose()
