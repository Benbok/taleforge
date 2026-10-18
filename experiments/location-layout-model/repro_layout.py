"""Воспроизведение 400 у location_layout: исходный запрос и варианты схемы, по одному изменению."""

import asyncio
import copy
import sys

from app.agents import layout_model as lm
from app.agents.llm import LiteLLMClient, parser_model_for
from tests.layout_plan_pilot import temple_mandate


def walk(node, fn):
    if isinstance(node, dict):
        fn(node)
        for v in node.values():
            walk(v, fn)
    elif isinstance(node, list):
        for v in node:
            walk(v, fn)


def drop(key):
    def f(n):
        n.pop(key, None)

    return f


def variants(tool):
    yield "original", tool
    bounded = copy.deepcopy(tool)
    bounded["function"]["parameters"]["properties"]["parts"]["maxItems"] = 12
    yield "bounded_parts", bounded
    for key in ("pattern", "additionalProperties", "maxItems", "minItems", "maxLength", "minimum", "maximum", "enum"):
        t = copy.deepcopy(bounded)
        walk(t, drop(key))
        yield f"no_{key}", t


async def main(which):
    m = temple_mandate()
    msgs = [{"role": "system", "content": lm.SYSTEM}, {"role": "user", "content": lm.brief(m)}]
    model = parser_model_for()
    llm = LiteLLMClient()
    for name, tool in variants(lm.spec(m)):
        if which and name not in which:
            continue
        try:
            r = await llm.complete(
                copy.deepcopy(msgs),
                model=model,
                tools=[tool],
                tool_choice="required",
                max_tokens=lm.MAX_OUT,
                temperature=0.7,
            )
            print(name, "OK", [t.name for t in r.tool_calls], r.tokens_in, r.tokens_out)
        except Exception as e:  # noqa: BLE001
            print(name, "FAIL", str(e)[:200].replace("\n", " "))


asyncio.run(main(sys.argv[1:]))
