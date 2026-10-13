"""Playtest regressions: required director answers and provider termination audit."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents.director import LlmNarrativeAuthor, decode_director_reply
from app.agents.llm import LiteLLMClient, LLMReply, ToolCall
from app.agents.master.turn import TurnMixin
from app.core.narrative.service import NarrativeService
from app.db.models import LlmCall, NarrativeWork
from app.db.narrative_jobs import SqlNarrativeJobs
from app.db.session import make_sessionmaker
from tests.narrative_helpers import FakeClock, boundary, snapshot
from tests.test_narrative_director import FakeDirectorLLM
from tests.test_narrative_jobs import _ensure_campaigns
from tests.test_narrative_service import FakeApplier, FakeReader
from tests.test_streamed_tool_calls import AsyncChunks


@pytest.mark.parametrize(
    "calls",
    [
        [],
        [ToolCall("c", "other_tool", {})],
        [ToolCall("c", "propose_adaptation", {})],
        [ToolCall("c", "propose_adaptation", {"__invalid_json__": "secret-payload"})],
        [ToolCall("c", "propose_adaptation", {"summary": " ", "operations": []})],
        [ToolCall("c", "propose_adaptation", {"summary": "No change", "operations": None})],
        [ToolCall("c", "propose_adaptation", {"summary": "Change", "operations": [{"kind": "bad"}]})],
    ],
)
def test_invalid_director_response_raises_and_records_consumed_tokens(calls):
    reports = []

    async def observe(report):
        reports.append(report)

    reply = LLMReply(text="", tool_calls=calls, tokens_in=1288, tokens_out=0, cost=0.01)
    author = LlmNarrativeAuthor(FakeDirectorLLM(reply), call_observer=observe)
    with pytest.raises(ValueError):
        asyncio.run(author.propose(snapshot()))
    assert len(reports) == 1
    assert reports[0].error is not None
    assert "secret-payload" not in reports[0].error
    assert (reports[0].tokens_in, reports[0].tokens_out, reports[0].cost) == (1288, 0, 0.01)


def test_decoder_requires_explicit_director_decision():
    with pytest.raises(ValueError):
        decode_director_reply(snapshot(), {})


@pytest.mark.parametrize("grounds", [None, {}, ["unsupported ground"], [{"kind": "invalid"}]])
def test_invalid_director_grounds_are_not_accepted_or_audited_as_success(grounds):
    reports = []

    async def observe(report):
        reports.append(report)

    reply = LLMReply(
        text="",
        tool_calls=[
            ToolCall("c", "propose_adaptation", {"summary": "No changes", "operations": [], "grounds": grounds})
        ],
    )
    with pytest.raises(ValueError):
        asyncio.run(LlmNarrativeAuthor(FakeDirectorLLM(reply), call_observer=observe).propose(snapshot()))
    assert reports[0].error is not None


def test_explicit_director_no_change_remains_valid():
    args = {"summary": "The completed scene gives no reason to change future events", "operations": []}
    reply = LLMReply(text="", tool_calls=[ToolCall("c", "propose_adaptation", args)])
    proposal = asyncio.run(LlmNarrativeAuthor(FakeDirectorLLM(reply)).propose(snapshot()))
    assert proposal.operations == ()
    assert proposal.summary == args["summary"]


def test_missing_director_answer_retries_within_call_budget_and_persists_error(client, monkeypatch):
    from app.agents import architect
    from app.core import campaigns

    async def model_of(*args):
        return "local", "test-model", None, 0.7

    monkeypatch.setattr(architect, "model_of", model_of)
    monkeypatch.setattr(campaigns, "master_seat", lambda _: None)

    async def run():
        maker = make_sessionmaker(client.app.state.engine)
        await _ensure_campaigns(maker, "camp-1")
        clock = FakeClock()
        jobs = SqlNarrativeJobs(maker)
        wid = await jobs.enqueue(boundary())
        author = LlmNarrativeAuthor(FakeDirectorLLM(LLMReply(text="", tokens_in=1288, cost=0.01)), session_maker=maker)
        service = NarrativeService(FakeReader(), author, FakeApplier(), jobs, clock)
        for attempt in (1, 2):
            report = await service.prepare_once("camp-1")
            assert report.reason_code == "author_error"
            async with maker() as s:
                row = await s.get(NarrativeWork, wid)
                assert row.status == "retry_wait"
                assert row.draft is None and row.receipt_event_id is None
                assert row.llm_calls == attempt
                calls = (await s.scalars(select(LlmCall).where(LlmCall.purpose == "director"))).all()
                assert len(calls) == attempt
                assert all(c.error and c.tokens_in == 1288 and c.cost == 0.01 for c in calls)
            clock.advance(6)
        await service.prepare_once("camp-1")
        async with maker() as s:
            row = await s.get(NarrativeWork, wid)
            assert row.status in {"failed", "rejected"}
            assert row.llm_calls == 2 and row.receipt_event_id is None
            assert len((await s.scalars(select(LlmCall))).all()) == 2

    asyncio.run(run())


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("finish_reason, blocked", [("length", False), ("content_filter", True)])
def test_provider_finish_reason_survives_normal_and_stream_reply(monkeypatch, stream, finish_reason, blocked):
    import litellm

    msg = SimpleNamespace(content="", tool_calls=[], model_dump=lambda **_: {"content": ""})
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
    response = SimpleNamespace(choices=[choice], model="test-model", usage=None)

    async def complete(**kwargs):
        if not stream:
            return response
        return AsyncChunks(
            [
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason=finish_reason)]
                )
            ]
        )

    async def push(_):
        pass

    monkeypatch.setattr(litellm, "acompletion", complete)
    monkeypatch.setattr(litellm, "stream_chunk_builder", lambda *a, **kw: response)
    monkeypatch.setattr(litellm, "completion_cost", lambda **kw: 0)
    reply = asyncio.run(LiteLLMClient().complete([], model="test-model", stream_callback=push if stream else None))
    assert getattr(reply, "finish_reason", None) == finish_reason
    assert getattr(reply, "blocked", None) is blocked


@pytest.mark.parametrize("stream", [False, True])
def test_provider_prompt_block_metadata_survives_reply(monkeypatch, stream):
    import litellm

    response = SimpleNamespace(
        choices=[],
        model="test-model",
        usage=None,
        provider_specific_fields={"prompt_feedback": {"block_reason": "SAFETY"}},
    )

    async def complete(**kwargs):
        return AsyncChunks([response]) if stream else response

    async def push(_):
        pass

    monkeypatch.setattr(litellm, "acompletion", complete)
    monkeypatch.setattr(litellm, "stream_chunk_builder", lambda *a, **kw: response)
    monkeypatch.setattr(litellm, "completion_cost", lambda **kw: 0)
    reply = asyncio.run(LiteLLMClient().complete([], model="test-model", stream_callback=push if stream else None))
    assert reply.text == ""
    assert getattr(reply, "blocked", None) is True
    assert getattr(reply, "blocked_metadata", None) == {"block_reason": "SAFETY"}


@pytest.mark.parametrize(
    "finish_reason, text, blocked, reason",
    [
        ("length", "", False, "empty_response"),
        ("content_filter", "", True, "empty_response"),
        ("stop", "   ", False, "empty_response"),
        ("stop", "Partial narration", True, "blocked_response"),
    ],
)
def test_master_accounts_invalid_narration_but_returns_reply(finish_reason, text, blocked, reason):
    reply = LLMReply(text=text, tokens_in=100, tokens_out=0, cost=0.01)
    reply.finish_reason = finish_reason
    reply.blocked = blocked
    reply.blocked_metadata = {"block_reason": "SAFETY"} if blocked else {}
    master = TurnMixin()
    master.llm = FakeDirectorLLM(reply)
    calls = []
    cfg = SimpleNamespace(temperature=0.7, settings={})
    result = asyncio.run(master._ask(calls, cfg, "cid", "seat", "turn", "narrate", [], None))
    assert result is reply
    assert len(calls) == 1
    assert calls[0].error is not None
    audit = json.loads(calls[0].error)
    assert audit["reason"] == reason
    assert audit["finish_reason"] == finish_reason
    assert audit["blocked"] is blocked
    assert calls[0].tokens_in == 100 and calls[0].cost == 0.01


def test_master_successful_stop_is_not_recorded_as_error():
    master = TurnMixin()
    reply = LLMReply(text="The gate opens.")
    reply.finish_reason = "stop"
    master.llm = FakeDirectorLLM(reply)
    calls = []
    cfg = SimpleNamespace(temperature=0.7, settings={})
    asyncio.run(master._ask(calls, cfg, "cid", "seat", "turn", "narrate", [], None))
    assert calls[0].error is None
