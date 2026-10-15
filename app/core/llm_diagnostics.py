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
