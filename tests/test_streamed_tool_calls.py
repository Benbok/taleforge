"""Regression test: streamed LiteLLM tool calls survive response collection."""

import asyncio
from types import SimpleNamespace

from app.agents.llm import _collect_stream


class AsyncChunks:
    def __init__(self, chunks):
        self.chunks = chunks

    def __aiter__(self):
        self._iter = iter(self.chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def test_collect_stream_preserves_tool_calls():
    tool = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="spawn_entity", arguments='{"template_id":"creature.skeleton"}'),
    )

    class Message:
        tool_calls = [tool]
        content = None

        def model_dump(self, exclude_none=True):
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "spawn_entity",
                            "arguments": '{"template_id":"creature.skeleton"}',
                        },
                    }
                ],
            }

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=Message())],
        model="test-model",
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=15),
    )
    chunks = AsyncChunks([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=None))])])
    fake_litellm = SimpleNamespace(
        stream_chunk_builder=lambda raw, messages: response,
        completion_cost=lambda completion_response: 0,
    )

    async def run():
        return await _collect_stream(fake_litellm, chunks, "test-model", [], lambda _: None, 0)

    result = asyncio.run(run())
    assert result.text == ""
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "spawn_entity"
    assert result.tool_calls[0].arguments == {"template_id": "creature.skeleton"}
    assert result.message["tool_calls"][0]["id"] == "call_1"
