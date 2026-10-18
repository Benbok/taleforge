import asyncio

from app.agents import layout_model as lm
from app.agents.llm import LiteLLMClient, parser_model_for
from app.core.layout.provider import DeterministicLayoutProvider
from tests.layout_plan_pilot import temple_mandate


def check(i):
    DeterministicLayoutProvider().propose(i, seed=7, root_id="root")


async def main():
    llm = LiteLLMClient()
    for label, m in (("holders", temple_mandate()), ("no_holders", temple_mandate(anchors=(), residents=()))):
        for run in range(2):
            msgs = []
            for call in range(2):
                intent, att, why = await lm.ask(llm, m, model=parser_model_for(), api_base=None, msgs=msgs, check=check)
                print(
                    label,
                    run,
                    call,
                    "OK" if intent else ("RETRY: " + (why or "")[:100] if why else "ERR: " + (att.error or "")[:100]),
                    f"${att.cost:.5f}",
                )
                if intent or not why:
                    break


asyncio.run(main())
