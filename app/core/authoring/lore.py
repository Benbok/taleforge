"""Structured world lore for an author project, stored in CampaignSecret.setting."""

import json
import re

from app.agents.architect import model_of
from app.agents.llm import LLMError
from app.core.llm_diagnostics import reply_metrics
from app.db.models import Campaign, LlmCall

LORE_KEYS = ("world", "factions", "history", "tone", "taboos")
SYSTEM = (
    "Ты автор настольной кампании. По анкете опиши мир строго JSON-объектом с ключами: "
    "world (строка), factions (список строк), history (строка), tone (строка), taboos (список строк). "
    "Без пояснений и без markdown."
)
MAX_TOKENS = 3000


class LoreError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def parse_lore(text: str) -> dict:
    body = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise LoreError("lore_invalid") from exc
    if not isinstance(data, dict) or not str(data.get("world") or "").strip():
        raise LoreError("lore_invalid")
    return {key: data[key] for key in LORE_KEYS if key in data}


async def generate_lore(svc, world_id: str, job_id: str) -> dict:
    """One model call; the transaction is not held while the model is thinking."""
    async with svc.maker() as s:
        world = await s.get(Campaign, world_id)
        _provider, model, api_base, temperature = await model_of(s, world)
        brief = json.dumps(world.brief or {}, ensure_ascii=False)
        await s.rollback()
    call = LlmCall(campaign_id=world_id, purpose="lore", model=model, author_job_id=job_id)
    try:
        reply = await svc.llm.complete(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Анкета: {brief}"}],
            model=model,
            max_tokens=MAX_TOKENS,
            temperature=min(max(temperature, 0.7), 1.0),
            api_base=api_base,
        )
    except LLMError as exc:
        call.error = str(exc)[:2000]
        await _save(svc, call)
        raise LoreError("llm_unavailable") from exc
    call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
    call.cost, call.latency_ms = reply.cost, reply.latency_ms
    for metric, value in reply_metrics(reply).items():
        setattr(call, metric, value)
    try:
        lore = parse_lore(reply.text)
    except LoreError as exc:
        call.error = exc.code
        await _save(svc, call)
        raise
    await _save(svc, call)
    return lore


async def _save(svc, call: LlmCall) -> None:
    async with svc.maker() as s:
        s.add(call)
        await s.commit()
