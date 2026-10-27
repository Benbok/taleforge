# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Режиссёр собран в приложении (F9, R10): create_app, обычный ход, штатное восстановление."""

from __future__ import annotations

import inspect
import time

import pytest
from sqlalchemy import select

from app.agents.llm import LLMReply, ToolCall
from app.core.narrative.contracts import BoundaryRecord, EvidenceRef
from app.db.models import Campaign, CampaignSecret, Event, LlmCall, NarrativeWork
from app.db.narrative_jobs import SqlNarrativeJobs
from app.db.session import make_sessionmaker
from tests.game import party, run
from tests.test_lead import set_plan
from tests.test_master import act
from tests.test_narrative_architect import initialized_plan
from tests.test_narrative_master import DONE, admin_g, dice, game_client, llm  # noqa: F401 — фикстуры

NEW_TITLE = "Союзный склеп"


def _director_reply(messages, tools):
    """Ответ режиссёра: пересмотр будущего узла третьего акта. Основание берёт сервер из задания."""
    args = {
        "summary": "Склеп становится местом переговоров",
        "operations": [
            {
                "kind": "revise_future_situation",
                "patch": {
                    "edits": [
                        {
                            "kind": "update_open_node",
                            "act_id": "act3",
                            "node_id": "n_crypt",
                            "fields": {"title": NEW_TITLE, "summary": "Переговоры с хранителем склепа"},
                        }
                    ]
                },
            }
        ],
    }
    call = ToolCall("call_dir", "propose_adaptation", args, "")
    return LLMReply(text="", tool_calls=[call], model="m", tokens_in=120, tokens_out=40)


def _is_director(req) -> bool:
    return any((t.get("function") or {}).get("name") == "propose_adaptation" for t in req.get("tools") or [])


def _setup(game_client, admin_g, settings, **settings_patch):
    c, (p1,), _hero = party(game_client, admin_g, narrative_mode="adaptive")
    cid = c["id"]
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    set_plan(settings, cid, initialized_plan())
    if settings_patch:

        async def patch(s):
            camp = await s.get(Campaign, cid)
            camp.settings = {**(camp.settings or {}), **settings_patch}
            await s.commit()

        run(settings, patch)
    return cid, p1


def _route_director(llm, director) -> list:
    """Вызовы режиссёра отвечает ``director`` (узнаются по инструменту), остальные — очередь хода мастера."""
    plain = llm.complete
    seen: list = []

    async def complete(messages, **kw):
        req = {"messages": messages, "tools": kw.get("tools")}
        if _is_director(req):
            seen.append(req)
            if director is None:
                raise AssertionError("режиссёр вызван, хотя не должен")
            reply = director(messages, kw.get("tools"))
            return await reply if inspect.isawaitable(reply) else reply
        return await plain(messages, **kw)

    llm.complete = complete
    return seen


def _close_act(game_client, llm, p1, cid, director=None) -> list:
    """Обычный ход мастера закрывает акт; возвращает запросы к режиссёру."""
    seen = _route_director(llm, director) if director is not None else []
    llm.replies += [
        {"tool_calls": [("end_act", {"outcome": "Отряд договорился с хранителем вместо боя"})]},
        DONE,
        DONE,
        {"text": "Хранитель склоняет голову: союз заключён."},
    ]
    act(game_client, p1, cid, "Предлагаю хранителю союз")
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    _settle(game_client.app.state.settings, cid)
    return seen


def _settle(settings, cid, timeout: float = 15.0) -> None:
    """Ждать, пока цикл восстановления (его будит сам ход) отпустит задание: wait_idle его не ждёт."""
    deadline = time.monotonic() + timeout
    while any(w.lease_token is not None for w in _works(settings, cid)):  # автор или применение в работе
        assert time.monotonic() < deadline, "задание режиссёра не отпущено"
        time.sleep(0.05)


def _node_title(settings, cid) -> str:
    async def go(s):
        plan = (await s.get(CampaignSecret, cid)).plot
        return next(n["title"] for a in plan["acts"] for n in a.get("nodes") or [] if n["id"] == "n_crypt")

    return run(settings, go)


def _works(settings, cid):
    """Задания закрытия акта; граница самого хода может поставить и другие."""

    async def go(s):
        q = select(NarrativeWork).where(NarrativeWork.campaign_id == cid, NarrativeWork.kind == "act_closed")
        return (await s.scalars(q)).all()

    return run(settings, go)


def _director_calls(settings, cid):
    async def go(s):
        q = select(LlmCall).where(LlmCall.campaign_id == cid, LlmCall.purpose == "director")
        return (await s.scalars(q)).all()

    return run(settings, go)


@pytest.mark.parametrize("patch", [{"replan": False}, {"spend_limit_usd": 0}, {"status": "ended"}])
def test_paused_director_keeps_job_and_never_calls_model(game_client, admin_g, llm, settings, patch):
    """Задание, поставленное раньше, ждёт: replan=false, исчерпанный бюджет или конец кампании не зовут модель."""
    cid, _p1 = _setup(game_client, admin_g, settings)

    async def queued(s):
        s.add(Event(id="evt-end-act-1", campaign_id=cid, tool="end_act", payload={"act_id": "act1"}))
        await s.commit()
        boundary = BoundaryRecord(
            campaign_id=cid,
            kind="act_closed",
            source_id="evt-end-act-1",
            scope="future",
            evidence_refs=(EvidenceRef(campaign_id=cid, kind="event", source_id="evt-end-act-1"),),
            session_budget_ref=f"sess_{cid}",
        )
        await SqlNarrativeJobs(make_sessionmaker(s.bind)).enqueue(boundary)
        camp = await s.get(Campaign, cid)
        if "status" in patch:
            camp.status = patch["status"]
        else:
            camp.settings = {**(camp.settings or {}), **patch}
        await s.commit()

    run(settings, queued)
    game_client.portal.call(game_client.app.state.master.recover)
    assert [w.status for w in _works(settings, cid)] == ["pending"]
    assert _director_calls(settings, cid) == []
    assert llm.director_requests == []


def _session_works(settings, cid):
    async def go(s):
        q = select(NarrativeWork).where(NarrativeWork.campaign_id == cid, NarrativeWork.kind == "session_closed")
        return (await s.scalars(q)).all()

    return run(settings, go)


def test_campaign_end_does_not_queue_director(game_client, admin_g, llm, settings):
    cid, _p1 = _setup(game_client, admin_g, settings)
    r = game_client.post(f"/api/campaigns/{cid}/session/end", headers=admin_g)
    assert r.status_code == 200, r.text
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    game_client.portal.call(game_client.app.state.master.recover)
    assert _session_works(settings, cid) == []
    assert llm.director_requests == []
