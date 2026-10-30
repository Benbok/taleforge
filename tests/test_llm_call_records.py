import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import select

from app.agents.llm import LLMReply, ToolCall
from app.agents.master.prompting.messages import decide_messages
from app.agents.master.universal import _call
from app.db.models import LlmCall
from tests.test_universal_master import prepare
from tests.test_universal_resolution import setup


class Provider:
    def __init__(self, reply):
        self.reply = reply

    async def complete(self, messages, **kwargs):
        return self.reply


def reply(**extra):
    call = ToolCall(id="1", name="submit_action", arguments={"effects": []})
    return LLMReply(text="", tool_calls=[call], tokens_in=1000, tokens_out=50, **extra)


def campaign():
    return SimpleNamespace(id="c", settings={}, seats=[SimpleNamespace(role="master", agent_config_id=None)])


async def recorded(tmp_path, purpose, payload, llm_reply):
    engine, maker = await setup(tmp_path)
    await prepare(maker)
    service = SimpleNamespace(maker=maker, llm=Provider(llm_reply))
    await _call(service, campaign(), None, purpose, payload)
    async with maker() as s:
        row = await s.scalar(select(LlmCall).where(LlmCall.purpose == purpose))
    await engine.dispose()
    return row


def test_the_cached_share_of_the_input_is_recorded(tmp_path):
    payload = decide_messages({"source": "иду", "scene": {"name": "Порт"}})
    row = asyncio.run(
        recorded(tmp_path, "exploration_decide", payload, reply(tokens_cached=700, reasoning_tokens=5, cost_known=True))
    )
    assert (row.tokens_cached, row.tokens_reasoning, row.cost_known) == (700, 5, True)


def test_unreported_cache_stays_unknown_not_zero(tmp_path):
    payload = decide_messages({"source": "иду"})
    row = asyncio.run(recorded(tmp_path, "exploration_decide", payload, reply()))
    assert row.tokens_cached is None


def test_decision_input_sizes_by_part_are_recorded(tmp_path):
    payload = decide_messages({"source": "иду", "scene": {"name": "Порт"}, "history": ["a" * 300]})
    row = asyncio.run(recorded(tmp_path, "exploration_decide", payload, reply()))
    sizes = row.diagnostics["request_size"]
    assert {"system", "schema", "context.scene", "context.history", "total"} <= set(sizes)
    assert sizes["context.history"] > 300


def test_other_calls_record_message_sizes_without_content(tmp_path):
    payload = [{"role": "system", "content": "правила"}, {"role": "user", "content": "СЕКРЕТНЫЙ ТЕКСТ"}]
    row = asyncio.run(recorded(tmp_path, "narrate", payload, LLMReply(text="рассказ", tokens_in=10)))
    assert row.diagnostics["message_sizes"]["blocks"]["message_1_user"]["chars"] == len("СЕКРЕТНЫЙ ТЕКСТ")
    assert "СЕКРЕТНЫЙ" not in json.dumps(row.diagnostics, ensure_ascii=False)
