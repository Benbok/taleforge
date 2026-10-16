"""Isolated evaluator adapters for context-only comparisons.

The adapters operate on captured assembler inputs. They do not change the
production checkout, mechanical flags, tool policy, model, dice, or actions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

CONTEXT_VARIANTS = ("legacy", "v1", "revised")
TOOLS_VARIANTS = ("full", "profile")
PRODUCT_VARIANTS = ("legacy", "optimized")


@dataclass(frozen=True)
class ExperimentConfig:
    kind: Literal["context", "tools", "product"]
    variants: tuple[str, ...]

    def __post_init__(self) -> None:
        allowed = {
            "context": CONTEXT_VARIANTS,
            "tools": TOOLS_VARIANTS,
            "product": PRODUCT_VARIANTS,
        }.get(self.kind)
        if allowed is None:
            raise ValueError(f"unknown experiment kind: {self.kind}")
        variants = CONTEXT_VARIANTS if self.variants == ("all",) and self.kind == "context" else self.variants
        if not variants or len(set(variants)) != len(variants) or any(variant not in allowed for variant in variants):
            raise ValueError(f"unknown variant for {self.kind}: {self.variants!r}")
        object.__setattr__(self, "variants", tuple(variants))


def package_for_variant(variant: str, source: dict) -> dict:
    """Render one deterministic, inspectable package from identical source input."""
    if variant not in CONTEXT_VARIANTS:
        raise ValueError(f"unknown context variant: {variant}")
    messages = [dict(message) for message in source.get("messages") or []]
    tools = [dict(tool) for tool in source.get("tools") or []]
    if variant == "legacy":
        rendered = [{"role": "system", "content": "\n\n".join(str(m.get("content") or "") for m in messages)}]
    elif variant == "v1":
        rendered = [
            {"role": "system", "content": "Role context:\n" + "\n".join(str(m.get("content") or "") for m in messages)},
            {"role": "user", "content": str(messages[-1].get("content") if messages else "")},
        ]
    else:
        rendered = messages
    canonical = {"variant": variant, "messages": rendered, "tools": tools}
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {**canonical, "digest": digest}


def effective_config(config: ExperimentConfig, variant: str) -> dict[str, object]:
    if variant not in config.variants:
        raise ValueError(f"variant {variant!r} is not selected by experiment")
    return {"kind": config.kind, "selected_variant": variant, "variants": list(config.variants)}

