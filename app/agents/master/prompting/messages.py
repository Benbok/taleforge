"""Build the master's request without database or provider side effects."""

import json
from copy import deepcopy

from app.agents.master.prompting.modules import compose_system
from app.agents.master.prompting.slicers import slice_context
from app.rules.universal.exploration import exploration_capabilities


def decide_messages(context: dict, repair: str | None = None, *, extra_blocks=()) -> list[dict]:
    data = {
        key: value
        for key, value in slice_context(context, context.get("source", ""), extra_blocks).items()
        if key != "repair"
    }
    return [
        {
            "role": "system",
            "content": compose_system(context)
            + "\n"
            + json.dumps({"capabilities": exploration_capabilities()}, ensure_ascii=False),
        },
        {
            "role": "user",
            "content": json.dumps({**data, "repair": repair}, ensure_ascii=False),
        },
    ]


def cacheable(messages: list[dict], model: str) -> list[dict]:
    """Anthropic's explicit cache marker; other providers retain their native format."""
    if not model.startswith(("anthropic/", "claude")):
        return messages
    result = deepcopy(messages)
    for message in result:
        if message["role"] == "system":
            content = message["content"]
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            if content:
                content[-1]["cache_control"] = {"type": "ephemeral"}
            message["content"] = content
    return result


def request_size(messages: list[dict], tool_schema: dict) -> dict[str, int]:
    """Serialized character counts, including JSON punctuation; these are not tokens."""
    sizes = {
        "system": sum(
            len(m["content"])
            if isinstance(m["content"], str)
            else sum(len(block.get("text", "")) for block in m["content"])
            for m in messages
            if m["role"] == "system"
        ),
        "schema": len(json.dumps(tool_schema, ensure_ascii=False)),
    }
    for message in messages:
        if message["role"] != "user":
            continue
        context = json.loads(message["content"])
        if not context:
            sizes["context.__framing__"] = sizes.get("context.__framing__", 0) + 2
        for key, value in context.items():
            # Each singleton includes two braces, accounting for the outer braces
            # and the equally long comma-space separators of the combined object.
            name = f"context.{key}"
            sizes[name] = sizes.get(name, 0) + len(json.dumps({key: value}, ensure_ascii=False))
    sizes["total"] = sum(sizes.values())
    return sizes
