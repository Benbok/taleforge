"""Учёт вызовов модели по фазам подготовки (спецификация 2026-10-12, §8): строка фазы и токены рассуждений."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

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
            cost=0.01,
        )

    assert _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=ScriptedLLM([reasoned]))) == "ready"
    (call,) = rows(settings, LlmCall, LlmCall.generation_id == ref)
    assert call.tokens_reasoning == 25 and call.tokens_out == 40


def test_litellm_reply_reads_reasoning_tokens():
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=7,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=3),
    )
    assert llm_mod.reasoning_of(usage) == 3
    assert llm_mod.reasoning_of(SimpleNamespace(prompt_tokens=1, completion_tokens=1)) == 0
    assert llm_mod.reasoning_of(None) == 0
