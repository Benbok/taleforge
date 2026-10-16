"""Content-free diagnostics. Size estimates never stand in for actual provider usage."""

from __future__ import annotations

import json
import math
from typing import Any


def prompt_sizes(blocks: dict[str, str], tools: list) -> dict:
    def size(text: str) -> dict[str, int]:
        return {
            "chars": len(text),
            "utf8_bytes": len(text.encode("utf-8")),
            "estimated_tokens": math.ceil(len(text) / 4),
        }

    return {
        "estimate_method": "chars/4-ceil",
        "blocks": {k: size(v) for k, v in blocks.items()},
        "tools": size(json.dumps(tools, ensure_ascii=False, sort_keys=True)),
    }


def reply_metrics(reply: Any) -> dict[str, Any]:
    """Common mapping for every LLMReply -> LlmCall persistence path."""
    return {
        "tokens_reasoning": reply.reasoning_tokens,
        "tokens_cached": reply.tokens_cached,
        "cost_known": reply.cost_known,
    }


def message_sizes(messages: list[dict], tools: list) -> dict:
    """Measure visible content and function payloads without inspecting provider reasoning."""
    blocks = {}
    for i, message in enumerate(messages):
        key = f"message_{i}_{message.get('role', 'unknown')}"
        content = message.get("content")
        blocks[key] = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        calls = message.get("tool_calls")
        if calls:
            # Select protocol fields explicitly: never serialize provider-specific metadata.
            public_calls = [
                {
                    "id": call.get("id"),
                    "type": call.get("type"),
                    "function": {name: (call.get("function") or {}).get(name) for name in ("name", "arguments")},
                }
                for call in calls
            ]
            blocks[f"{key}_tool_calls"] = json.dumps(public_calls, ensure_ascii=False)
    return prompt_sizes(blocks, tools)


def retry_metrics(retry_count: int = 0, retry_reasons: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return bounded, content-free retry diagnostics for one provider call."""
    reasons = tuple(dict.fromkeys(reason for reason in retry_reasons if isinstance(reason, str) and reason))
    return {
        "retry_count": max(0, int(retry_count)),
        "retry_reasons": list(reasons),
    }
