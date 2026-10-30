"""Build the master's request without database or provider side effects."""

import json

from app.rules.universal.exploration import exploration_capabilities


def decide_messages(context: dict, repair: str | None = None) -> list[dict]:
    # Local import keeps the prompt owned by exploration during the measurement phase.
    from app.agents.master.exploration import SYSTEM

    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {**context, "capabilities": exploration_capabilities(), "repair": repair}, ensure_ascii=False
            ),
        },
    ]


def request_size(messages: list[dict], tool_schema: dict) -> dict[str, int]:
    """Serialized character counts, including JSON punctuation; these are not tokens."""
    sizes = {
        "system": sum(len(m["content"]) for m in messages if m["role"] == "system"),
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
