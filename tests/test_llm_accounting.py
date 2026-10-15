"""Учёт вызовов модели по фазам подготовки (спецификация 2026-10-12, §8): строка фазы и токены рассуждений."""

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config

from app.agents import llm as llm_mod
from app.agents.llm import LLMReply, ScriptedLLM
from app.core.world_generation.service import Orchestrator
from app.db.models import LlmCall
from app.gateway.coordination import InMemoryCoordination
from tests.test_master import rows
from tests.test_scene_model import _campaign, _named
from tests.test_world_generation import _fast_retry, _prepare, _room  # noqa: F401 — фикстура


def test_paid_usage_survives_world_transaction_rollback(settings):
    from app.agents.master.turn import TurnMixin
    from app.db.models import AgentConfig, Campaign, User
    from app.db.session import make_engine, make_sessionmaker

    maker = make_sessionmaker(make_engine(settings.database_url))
    reply = LLMReply(
        text="invalid output",
        model="m",
        tokens_in=100,
        tokens_out=40,
        reasoning_tokens=25,
        tokens_cached=80,
        cost=0.01,
        cost_known=True,
        finish_reason="length",
    )

    class Harness(TurnMixin):
        pass

    master = Harness()
    master.maker = maker
    master.llm = ScriptedLLM([reply])

    async def check():
        async with maker() as s:
            # Minimal campaign is sufficient to exercise the real independent call writer.
            s.add(User(id="u_accounting", name="accounting", password_hash="unused"))
            await s.flush()
            s.add(Campaign(id="c_accounting", name="accounting", owner_id="u_accounting", ruleset_version="1"))
            await s.commit()
        calls = []
        async with maker() as s:
            campaign = await s.get(Campaign, "c_accounting")
            campaign.name = "must roll back"
            await master._ask(
                calls,
                AgentConfig(temperature=0.2),
                "c_accounting",
                "seat",
                "turn",
                "decide",
                [{"role": "user", "content": "private prompt"}],
                None,
            )
            await s.flush()
            await s.rollback()
        await master._save_calls(calls)
        async with maker() as s:
            from sqlalchemy import select

            call = (await s.scalars(select(LlmCall).where(LlmCall.campaign_id == "c_accounting"))).one()
            assert (await s.get(Campaign, "c_accounting")).name == "accounting"
            assert (call.tokens_in, call.tokens_out, call.tokens_reasoning, call.tokens_cached) == (100, 40, 25, 80)
            assert call.cost == 0.01 and call.cost_known is True
            assert "incomplete_response" in call.error
            assert "private prompt" not in str(call.diagnostics)

    asyncio.run(check())


@pytest.mark.parametrize("cost,known", [(0.0, True), (0.0, False), (0.01, True)])
def test_director_keeps_reported_cost_without_repricing(monkeypatch, cost, known):
    import litellm

    from app.agents.director import LlmNarrativeAuthor
    from tests.test_narrative_director import FakeDirectorLLM, approx_tokens, snapshot

    reports = []
    reply = LLMReply(
        text="",
        model="m",
        tokens_in=100,
        tokens_out=40,
        cost=cost,
        cost_known=known,
        tool_calls=[
            llm_mod.ToolCall("tc", "propose_adaptation", {"summary": "No changes", "grounds": [], "operations": []})
        ],
    )
    monkeypatch.setattr(litellm, "cost_per_token", lambda **_: (0.01, 0.02))

    async def observer(report):
        reports.append(report)

    author = LlmNarrativeAuthor(
        FakeDirectorLLM(reply), "m", token_counter=approx_tokens, timeout_seconds=90, call_observer=observer
    )
    asyncio.run(author.propose(snapshot()))
    assert reports[0].cost == cost


def test_llm_call_migration_upgrade_and_downgrade(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    db_path = tmp_path / "calls.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    def columns() -> set[str]:
        with sqlite3.connect(db_path) as db:
            return {r[1] for r in db.execute("PRAGMA table_info(llm_calls)").fetchall()}

    command.upgrade(config, "0025")
    assert "generation_id" not in columns()
    command.upgrade(config, "0026")
    assert {"generation_id", "tokens_reasoning"} <= columns()
    command.downgrade(config, "0025")
    assert "generation_id" not in columns() and "tokens_reasoning" not in columns()


def test_scene_generation_call_is_tied_to_its_phase(client, admin, settings):
    cid = _campaign(client, admin, settings)
    _room_id, ref = _room(settings, cid)

    def reasoned(messages, tools):
        got = _named(messages, tools)
        return LLMReply(
            text="",
            tool_calls=[llm_mod.ToolCall("c1", got["tool_calls"][0][0], got["tool_calls"][0][1])],
            model="m",
            tokens_in=100,
            tokens_out=40,
            reasoning_tokens=25,
            tokens_cached=80,
            cost_known=True,
            cost=0.01,
        )

    assert _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=ScriptedLLM([reasoned]))) == "ready"
    (call,) = rows(settings, LlmCall, LlmCall.generation_id == ref)
    assert call.tokens_reasoning == 25 and call.tokens_out == 40
    assert call.tokens_cached == 80 and call.cost_known is True


def test_litellm_reply_reads_reasoning_tokens():
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=7,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=3),
    )
    assert llm_mod.reasoning_of(usage) == 3
    assert llm_mod.reasoning_of(SimpleNamespace(prompt_tokens=1, completion_tokens=1)) == 0
    assert llm_mod.reasoning_of(None) == 0


@pytest.mark.parametrize(
    "usage,expected",
    [
        ({"prompt_tokens_details": {"cached_tokens": 80}}, 80),
        (SimpleNamespace(prompt_tokens_details=SimpleNamespace(cached_tokens=0)), 0),
        ({"cache_read_input_tokens": 80}, 80),
        ({"prompt_tokens_details": {}}, None),
        (None, None),
    ],
)
def test_cached_tokens_preserve_unknown(usage, expected):
    assert llm_mod.cached_tokens_of(usage) == expected


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("price", [0.01, 0.0, None, "error"])
def test_provider_usage_and_price_coverage(monkeypatch, stream, price):
    import litellm

    msg = SimpleNamespace(content="ok", tool_calls=[], model_dump=lambda **_: {"content": "ok"})
    full = SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason="stop")],
        model="test/model",
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=40,
            prompt_tokens_details=SimpleNamespace(cached_tokens=80),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=25),
        ),
    )

    async def chunks():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))])

    async def provider(**kwargs):
        return chunks() if kwargs.get("stream") else full

    def cost(**kwargs):
        if price == "error":
            raise ValueError("unknown price")
        return price

    async def callback(text):
        pass

    monkeypatch.setattr(litellm, "acompletion", provider)
    monkeypatch.setattr(litellm, "stream_chunk_builder", lambda *a, **k: full)
    monkeypatch.setattr(litellm, "completion_cost", cost)
    reply = asyncio.run(
        llm_mod.LiteLLMClient().complete(
            [{"role": "user", "content": "hello"}],
            model="test/model",
            stream_callback=callback if stream else None,
        )
    )
    assert (reply.tokens_in, reply.tokens_cached, reply.tokens_out, reply.reasoning_tokens) == (100, 80, 40, 25)
    assert reply.cost_known is (price in (0.0, 0.01))


def test_usage_coverage_migration_preserves_historical_unknown(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    db_path = tmp_path / "coverage.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    command.upgrade(config, "0030")
    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO llm_calls "
            "(id,purpose,model,tokens_in,tokens_out,tokens_reasoning,cost,latency_ms,created_at) "
            "VALUES ('old','decide','m',100,40,25,0,1,CURRENT_TIMESTAMP)"
        )
    command.upgrade(config, "0031")
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT tokens_cached,cost_known,diagnostics FROM llm_calls").fetchone() == (None, None, None)
    command.downgrade(config, "0030")
    with sqlite3.connect(db_path) as db:
        assert "cost_known" not in {r[1] for r in db.execute("PRAGMA table_info(llm_calls)")}
