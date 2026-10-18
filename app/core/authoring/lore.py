"""Structured world lore for an author project, stored in CampaignSecret.setting["lore"].

The model submits lore through a tool call with a schema; the server checks it and asks once more with
the errors. The plot stage then receives this lore as input (app/agents/architect.py).
"""

import asyncio
import json
import os

from app.agents.architect import model_of
from app.agents.llm import LLMError, model_for
from app.core.llm_diagnostics import reply_metrics
from app.db.models import Campaign, LlmCall

TOOL = "submit_world_lore"
ATTEMPTS = 2
NETWORK_RETRIES = 3  # an unstable route to the provider drops TLS now and then; retry before giving up
MAX_TOKENS = 12000
SYSTEM = (
    "Ты автор мира для настольной ролевой кампании (D&D 5e, на русском). По анкете автора создай подробный, "
    "внутренне согласованный мир, на котором потом будет построен сюжет: обзор, эпоху и магию, крупные области, "
    "хронологию ключевых событий, фракции с целями и отношениями, ключевые фигуры, текущую ситуацию и тайны мира. "
    "Пиши конкретно: имена, места, причины и последствия, без общих слов. Сдай результат вызовом submit_world_lore."
)
REQUIRED = (
    "overview",
    "era_and_magic",
    "regions",
    "history",
    "factions",
    "figures",
    "current_situation",
    "mysteries",
    "tone",
)


def _s(desc: str, max_length: int = 2000) -> dict:
    return {"type": "string", "description": desc, "maxLength": max_length}


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


def _list(item: dict, lo: int, hi: int, desc: str = "") -> dict:
    out = {"type": "array", "minItems": lo, "maxItems": hi, "items": item}
    return {**out, "description": desc} if desc else out


def tool_spec() -> dict:
    schema = _obj(
        {
            "overview": _s("Обзор мира: 2–4 абзаца — что это за мир, чем живёт, в чём его своеобразие.", 4000),
            "era_and_magic": _s("Эпоха, уровень технологий, место магии и богов, что здесь считается нормой."),
            "regions": _list(
                _obj({"id": _s("id латиницей: reg_*", 64), "name": _s("Название", 80), "description": _s("2–3 фразы")},
                     ["id", "name", "description"]),
                2, 6,
            ),
            "history": _list(
                _obj({"when": _s("Когда", 80), "event": _s("Что случилось и к чему привело", 600)}, ["when", "event"]),
                4, 8, "Хронология от давних событий к недавним.",
            ),
            "factions": _list(
                _obj(
                    {
                        "name": _s("Название", 80),
                        "goal": _s("Чего добивается", 400),
                        "resources": _s("Чем располагает", 300),
                        "relations": _s("С кем враждует или союзничает", 400),
                        "secret": _s("Что скрывает", 300),
                    },
                    ["name", "goal", "relations"],
                ),
                2, 5,
            ),
            "figures": _list(
                _obj({"name": _s("Имя", 80), "role": _s("Кто это", 200), "motive": _s("Чего хочет и почему", 400)},
                     ["name", "role", "motive"]),
                2, 6,
            ),
            "current_situation": _s("Что происходит прямо сейчас и почему это касается героев.", 2000),
            "mysteries": _list(_s("Тайна мира", 400), 2, 5),
            "tone": _s("Тон и атмосфера", 300),
            "taboos": {"type": "array", "maxItems": 8, "items": _s("Чего избегать", 200)},
        },
        list(REQUIRED),
    )  # fmt: skip
    return {"type": "function", "function": {"name": TOOL, "description": "Сдать лор мира.", "parameters": schema}}


KEYS = tuple(tool_spec()["function"]["parameters"]["properties"])


class LoreError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def check_lore(data) -> tuple[dict | None, list[str]]:
    """Server-side check: the schema is a request to the model, not a guarantee."""
    if not isinstance(data, dict):
        return None, ["лор должен быть объектом"]
    errors = []
    if len(str(data.get("overview") or "").strip()) < 200:
        errors.append("overview слишком короткий: нужен обзор в 2–4 абзаца")
    for key, need in (("history", 4), ("factions", 2), ("regions", 2), ("figures", 2), ("mysteries", 2)):
        items = data.get(key)
        if not isinstance(items, list) or len(items) < need:
            errors.append(f"{key}: нужно не меньше {need}")
    if any(not isinstance(f, dict) or not f.get("goal") or not f.get("relations") for f in data.get("factions") or []):
        errors.append("у каждой фракции нужны goal и relations")
    if not str(data.get("current_situation") or "").strip():
        errors.append("current_situation: что происходит сейчас")
    if errors:
        return None, errors
    return {k: data[k] for k in KEYS if k in data}, []


def author_model(default: str) -> str:
    """AUTHOR_MODEL in the environment selects a stronger model for authoring; otherwise the master's model."""
    name = os.environ.get("AUTHOR_MODEL", "").strip()
    return model_for(None, name) if name else default


async def generate_lore(svc, world_id: str, job_id: str) -> dict:
    """The transaction is not held while the model is thinking; every attempt is recorded with its cost."""
    async with svc.maker() as s:
        world = await s.get(Campaign, world_id)
        _provider, model, api_base, temperature = await model_of(s, world)
        brief = json.dumps(world.brief or {}, ensure_ascii=False)
        title = world.name
        await s.rollback()
    model = author_model(model)
    msgs: list[dict] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Название приключения: {title}\nАнкета автора: {brief}"},
    ]
    calls: list[LlmCall] = []
    try:
        for _ in range(ATTEMPTS):
            for retry in range(NETWORK_RETRIES):
                call = LlmCall(campaign_id=world_id, purpose="lore", model=model, author_job_id=job_id)
                calls.append(call)
                try:
                    reply = await svc.llm.complete(
                        msgs,
                        model=model,
                        tools=[tool_spec()],
                        tool_choice="required",
                        max_tokens=MAX_TOKENS,
                        temperature=min(max(temperature, 0.7), 1.0),
                        api_base=api_base,
                    )
                    break
                except LLMError as exc:
                    call.error = str(exc)[:2000]
                    if retry == NETWORK_RETRIES - 1:
                        raise LoreError("llm_unavailable") from exc
                    await asyncio.sleep(2 * (retry + 1))
            call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
            call.cost, call.latency_ms = reply.cost, reply.latency_ms
            for metric, value in reply_metrics(reply).items():
                setattr(call, metric, value)
            tc = next((t for t in reply.tool_calls if t.name == TOOL), None)
            if tc is None:
                call.error = f"модель не вызвала {TOOL}"
                msgs.append(reply.message or {"role": "assistant", "content": reply.text})
                msgs.append({"role": "user", "content": f"Сдай лор вызовом {TOOL}."})
                continue
            lore, errors = check_lore(tc.arguments)
            if lore is not None:
                return lore
            call.error = "; ".join(errors)[:2000]
            msgs.append(reply.message or {"role": "assistant", "content": reply.text or ""})
            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({"ok": False, "errors": errors, "hint": "исправь и сдай лор целиком"},
                                          ensure_ascii=False),
                }
            )  # fmt: skip
        raise LoreError("lore_invalid")
    finally:
        async with svc.maker() as s:
            s.add_all(calls)
            await s.commit()
