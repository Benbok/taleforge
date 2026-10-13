"""Живой замер структуры пилота (спецификация 2026-10-12, §8, §10): один вызов технической модели по мандату храма
и поля, без БД. Печатает токены (и рассуждений), цену, задержку, качество и устройство. Запуск только явно:

    TALEFORGE_LIVE_PILOT=1 uv run python tools/pilot_location_layout.py

Ключи провайдера — из обычного .env проекта. В CI и тестах не запускается."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> int:
    if os.environ.get("TALEFORGE_LIVE_PILOT") != "1":
        print("живой замер выключен: задайте TALEFORGE_LIVE_PILOT=1")
        return 2
    from app.agents import layout_model
    from app.agents.llm import LiteLLMClient, parser_model_for
    from app.core.layout.provider import DeterministicLayoutProvider
    from tests.layout_plan_pilot import temple_mandate

    m = temple_mandate()
    provider = DeterministicLayoutProvider()
    msgs: list = []
    total = {"tokens_in": 0, "tokens_out": 0, "tokens_reasoning": 0, "cost": 0.0, "latency_ms": 0}
    for attempt_no in (1, 2):
        intent, attempt, retry = await layout_model.ask(
            LiteLLMClient(),
            m,
            model=parser_model_for(),
            api_base=None,
            msgs=msgs,
            check=lambda i: provider.propose(i, seed=12345, root_id="root"),
        )
        for k in total:
            total[k] += getattr(attempt, k)
        print(
            f"попытка {attempt_no}: {attempt.model} in={attempt.tokens_in} out={attempt.tokens_out} "
            f"reasoning={attempt.tokens_reasoning} cost={attempt.cost:.5f} {attempt.latency_ms} мс "
            f"ошибка={attempt.error or '-'}"
        )
        if intent is not None:
            bp = provider.propose(intent, seed=12345, root_id="root")
            print("принято:", ", ".join(f"{a.area_ref}({a.cols}x{a.rows}, ур.{a.level})" for a in bp.areas))
            break
        if retry is None:
            break
    else:
        print("модель не уложилась в две попытки: в игре будет детерминированный fallback")
    print("итого:", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
