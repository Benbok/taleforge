"""Tests for director LLM author, prompt packing, and decoding (Task 13)."""

from typing import Any

import pytest

from app.agents.director import (
    LlmNarrativeAuthor,
    decode_director_reply,
    pack_director_input,
)
from app.agents.llm import LLMReply, ToolCall
from app.core.narrative.contracts import (
    AuthorCallReport,
    FactRef,
    FactState,
    NarrativeSnapshot,
    SnapshotRef,
)
from tests.narrative_helpers import snapshot


def snapshot_with_required_dependency_too_large() -> NarrativeSnapshot:
    """Creates a snapshot whose required fact dependency is so huge it cannot fit within 6000 tokens."""
    snap_ref = SnapshotRef(
        kind="event",
        source_id="evt-huge",
        typed_address="campaign:huge-npc:motivation",
    )
    huge_fact_ref = FactRef(
        campaign_id="camp-1",
        namespace="campaign",
        subject_id="huge-npc",
        key="motivation",
        version=1,
        snapshot_ref=snap_ref,
    )
    huge_fact = FactState(
        ref=huge_fact_ref,
        kind="intent",
        temporal_semantics="current_state",
        freedom="committed",
        value="A" * 7000,  # 7000 characters with token_counter=len will exceed 6000
        audience=("party",),
        depends_on=(),
    )
    return snapshot(
        actors=("huge-npc",),
        facts=(huge_fact,),
    )


class FakeDirectorLLM:
    """Mock LLM returning predefined reply."""

    def __init__(self, reply: LLMReply) -> None:
        self._reply = reply
        self.last_messages: list[dict[str, Any]] = []
        self.last_tools: list[dict[str, Any]] | None = None

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        api_base: str | None = None,
        stream_callback: Any = None,
        thinking: bool = True,
    ) -> LLMReply:
        self.last_messages = messages
        self.last_tools = tools
        return self._reply


def test_director_failure_report_does_not_store_provider_exception_text():
    import asyncio

    class BrokenLLM:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("secret-provider-test-marker")

    reports = []

    async def observe(report):
        reports.append(report)

    author = LlmNarrativeAuthor(BrokenLLM(), call_observer=observe)
    with pytest.raises(RuntimeError):
        asyncio.run(author.propose(snapshot()))
    assert len(reports) == 1
    assert reports[0].error == "RuntimeError"
    assert "secret-provider-test-marker" not in repr(reports)


def test_context_limit_does_not_turn_omitted_fact_into_freedom():
    snap = snapshot_with_required_dependency_too_large()
    packed = pack_director_input(snap, token_counter=len, max_tokens=6000)
    assert packed.estimated_input_tokens <= 6000
    assert not packed.complete_for_edit
    assert packed.permitted_refs == ()


def test_pack_director_input_within_budget():
    snap = snapshot()
    packed = pack_director_input(snap, token_counter=len, max_tokens=6000)
    assert packed.estimated_input_tokens <= 6000
    assert packed.complete_for_edit
    assert len(packed.messages) >= 2  # system + user
    assert "name" in packed.tool_schema or "function" in packed.tool_schema
    assert "npc-1" in packed.permitted_refs


def test_decode_director_reply_valid():
    snap = snapshot()
    arguments = {
        "grounds": [
            {
                "kind": "divergence",
                "evidence_refs": [{"campaign_id": "camp-1", "kind": "event", "source_id": "evt-1"}],
                "subject_refs": ["npc-1"],
                "confidence": "explicit",
            }
        ],
        "summary": "Развить сюжетную нить союзников",
        "operations": [
            {
                "kind": "develop_actor_role",
                "entity_id": "npc-1",
                "new_role": "Лидер ополчения",
            }
        ],
    }
    proposal = decode_director_reply(snap, arguments)
    assert proposal.proposal_id == snap.proposal_id
    assert proposal.source == snap.source
    assert proposal.base == snap.base
    assert len(proposal.operations) == 1
    assert proposal.summary == "Развить сюжетную нить союзников"


def test_decode_director_reply_no_change():
    snap = snapshot()
    arguments = {
        "grounds": [],
        "summary": "Изменения не требуются",
        "operations": [],
    }
    proposal = decode_director_reply(snap, arguments)
    assert proposal.proposal_id == snap.proposal_id
    assert proposal.operations == ()
    assert proposal.summary == "Изменения не требуются"


def test_decode_director_reply_rejects_foreign_ref():
    snap = snapshot(actors=("npc-1",))
    arguments = {
        "grounds": [],
        "summary": "Попытка изменить неизвестного актера",
        "operations": [
            {
                "kind": "develop_actor_role",
                "entity_id": "npc-alien",  # Not in snap
                "new_role": "Шпион",
            }
        ],
    }
    with pytest.raises(ValueError, match="not permitted"):
        decode_director_reply(snap, arguments)


def test_llm_narrative_author_propose():
    import asyncio

    snap = snapshot()
    tool_args = {
        "grounds": [
            {
                "kind": "divergence",
                "evidence_refs": [{"campaign_id": "camp-1", "kind": "event", "source_id": "evt-1"}],
                "subject_refs": ["npc-1"],
                "confidence": "explicit",
            }
        ],
        "summary": "Режиссёр предлагает укрепить оборону",
        "operations": [
            {
                "kind": "develop_actor_role",
                "entity_id": "npc-1",
                "new_role": "Командир",
            }
        ],
    }
    reply = LLMReply(
        text="",
        tool_calls=[
            ToolCall(
                id="call-1",
                name="propose_adaptation",
                arguments=tool_args,
            )
        ],
        model="test-director-model",
        tokens_in=100,
        tokens_out=50,
        cost=0.01,
        latency_ms=350,
    )
    llm = FakeDirectorLLM(reply)

    observed_reports: list[AuthorCallReport] = []

    async def observer(report: AuthorCallReport) -> None:
        observed_reports.append(report)

    author = LlmNarrativeAuthor(
        llm,
        "test-director-model",
        token_counter=len,
        timeout_seconds=90,
        call_observer=observer,
    )

    async def _run():
        prop = await author.propose(snap)
        assert prop.summary == "Режиссёр предлагает укрепить оборону"
        assert len(prop.operations) == 1
        assert len(observed_reports) == 1
        report = observed_reports[0]
        assert report.model == "test-director-model"
        assert report.tokens_in == 100
        assert report.tokens_out == 50
        assert report.error is None

    asyncio.run(_run())


def test_llm_narrative_author_incomplete_context_returns_no_change():
    import asyncio

    snap = snapshot_with_required_dependency_too_large()

    reply = LLMReply(text="")
    llm = FakeDirectorLLM(reply)

    author = LlmNarrativeAuthor(
        llm,
        "test-director-model",
        token_counter=len,
        timeout_seconds=90,
    )

    async def _run():
        prop = await author.propose(snap)
        assert prop.operations == ()
        assert (
            "omitted" in prop.summary
            or "incomplete" in prop.summary
            or "no_change" in prop.summary
            or "контекст" in prop.summary.lower()
        )
        # LLM should not even have been called because packed was incomplete
        assert len(llm.last_messages) == 0

    asyncio.run(_run())
