"""Isolated evaluator adapters for context-only comparisons.

The adapters operate on captured assembler inputs. They do not change the
production checkout, mechanical flags, tool policy, model, dice, or actions.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
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
    """Freeze dispatched inputs, including assistant/tool messages, without rewriting."""
    if variant not in CONTEXT_VARIANTS + TOOLS_VARIANTS + PRODUCT_VARIANTS:
        raise ValueError(f"unknown variant: {variant}")
    canonical = {"messages": deepcopy(source.get("messages") or []), "tools": deepcopy(source.get("tools") or [])}
    digest = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {**canonical, "variant": variant, "digest": digest}


def historical_assembler():
    """Load the pinned dbfdc65 assembler with its own historical template loader."""
    import jinja2

    from tools.context_eval_history import prompt_context

    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(Path(__file__).with_name("context_eval_history") / "prompts"),
        autoescape=False,
        keep_trailing_newline=False,
    )
    prompt_context.render = lambda name, **values: environment.get_template(name).render(**values).strip()
    return prompt_context


async def assemble_variant(variant, ctx, cfg, *, role, inputs, revised=None):
    """Dispatch at the assembler input seam, before the tool conversation begins.

    dbfdc65's v1 caller passed the full legacy request after removing action refs
    and resolution (unless uncertain). Current callers split that request into
    named inputs, so feeding their shorter request straight into v1 loses context.
    Live mechanics and tool policy are deliberately shared by all three arms.
    """
    from app.agents.master import prompt_context

    if variant == "revised":
        return await (revised or prompt_context.build_prompt_bundle)(ctx, cfg, role=role, inputs=inputs)
    if variant not in {"legacy", "v1"}:
        raise ValueError(f"unknown context variant: {variant}")
    history = historical_assembler()
    legacy = deepcopy(inputs.get("legacy_messages"))
    if legacy is None:
        if role != "voice_line":
            raise ValueError(f"historical {role} requires legacy_messages")
        legacy = [
            {"role": "system", "content": ""},
            {"role": "user", "content": inputs.get("packet", inputs.get("request", ""))},
        ]
    values = getattr(ctx, "_narration_prompt_values", None) if role in {"narrate", "voice_line"} else None
    if values is None:
        values = await history.master_prompt_values(ctx, cfg)
    legacy[0]["content"] = history.render("master_system.j2", **values)
    if inputs.get("mood") and role in {"narrate", "voice_line"}:
        legacy[0]["content"] += inputs["mood"]
    if variant == "legacy":
        return prompt_context.PromptBundle(
            legacy,
            {},
            version="dbfdc65-legacy",
            assembly_path="legacy",
            selection_applied=False,
        )
    request = legacy[1]["content"]
    if role == "decide" and not inputs.get("uncertain"):
        request = history.without_context_block(
            history.without_action_context(request),
            inputs.get("resolution", ""),
        )
    historical_inputs = {"request": request, "legacy_messages": legacy}
    for key in ("mood", "uncertain", "resolution"):
        if key in inputs:
            historical_inputs[key] = inputs[key]
    bundle = await history.build_prompt_bundle(ctx, cfg, role=role, inputs=historical_inputs)
    return prompt_context.PromptBundle(
        bundle.messages,
        bundle.blocks,
        version="dbfdc65-role-context-v1",
        fallback_reason=bundle.fallback_reason,
    )


def effective_config(config: ExperimentConfig, variant: str) -> dict[str, object]:
    if variant not in config.variants:
        raise ValueError(f"variant {variant!r} is not selected by experiment")
    return {"kind": config.kind, "selected_variant": variant, "variants": list(config.variants)}


def context_quality(case: dict, packets: tuple | list) -> dict:
    """Observe recall/privacy against today's rubric without changing historical input."""
    text = {}
    for packet in packets:
        text.setdefault(packet["purpose"], [])
        text[packet["purpose"]].extend(message.get("content") or "" for message in packet["messages"])
    text = {role: "\n".join(parts) for role, parts in text.items()}
    roles = set(case["required_facts_by_role"]) | set(case["forbidden_facts_by_role"])
    result = {}
    for role in sorted(roles):
        required = [
            value
            for marker in case["required_facts_by_role"].get(role, [])
            for value in ([request["text"] for request in case["requests"]] if marker == "request" else [marker])
        ]
        result[role] = {
            "called": role in text,
            "missing_required": [marker for marker in required if marker not in text.get(role, "")],
            "present_forbidden": [
                marker for marker in case["forbidden_facts_by_role"].get(role, []) if marker in text.get(role, "")
            ],
        }
    return result
