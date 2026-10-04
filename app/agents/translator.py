"""Переводчик готовых приключений: книга PDF → модуль поверх SRD (app/core/modules.py).

Работает в фоне после загрузки книги админом: текст из PDF, разбор моделью с проверками сервера (до ATTEMPTS
попыток, ошибки возвращаются модели), потом по каждой карте вызов модели с картинкой — найти номера комнат.
Модель — по умолчанию из «Моделей ИИ», вызовы пишутся в расходы с назначением module_import и module_map.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path

from app.agents.architect import _assistant
from app.agents.llm import LLMError, model_for
from app.core import modules
from app.core.campaigns import default_model_profile
from app.db.models import AdventureModule, LlmCall

log = logging.getLogger(__name__)

ATTEMPTS = 3
MAP_ATTEMPTS = 2
MAX_TOKENS = 32000
MAP_TOKENS = 4000
BUSY = ("reading", "translating", "mapping")


def folder(media_dir: Path, module_id: str) -> Path:
    return Path(media_dir) / "modules" / module_id


async def _model(s) -> tuple[str, str | None]:
    p = await default_model_profile(s)
    if p is not None:
        return model_for(p.provider, p.model or None), p.api_base
    return model_for(), None


async def _set(svc, module_id: str, **fields) -> AdventureModule | None:
    async with svc.maker() as s:
        m = await s.get(AdventureModule, module_id)
        if m is None:
            return None
        for k, v in fields.items():
            setattr(m, k, v)
        await s.commit()
        return m


def _log(call: LlmCall, reply) -> None:
    call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
    call.cost, call.latency_ms = reply.cost, reply.latency_ms


async def run_import(svc, module_id: str, media_dir: Path, packs_root: Path) -> None:
    """Полный разбор: текст, переводчик, карты. Итог — статус review или failed с причиной."""
    try:
        base = folder(media_dir, module_id)
        await _set(svc, module_id, status="reading", error=None)
        text, pages = await asyncio.to_thread(modules.extract_text, base / "source.pdf")
        (base / "source.txt").write_text(text, encoding="utf-8")
        m = await _set(svc, module_id, status="translating", pages=pages, text_chars=len(text))
        if m is None:
            return
        draft, warnings, errors = await translate(svc, module_id, text, m.note, packs_root)
        if draft is None:
            await _set(svc, module_id, status="failed", error="; ".join(errors)[:2000])
            return
        title = str(draft.get("title") or m.title)[:255]
        await _set(svc, module_id, status="mapping", draft=draft, warnings=warnings, title=title, slug=draft["slug"])
        await run_maps(svc, module_id, media_dir)
    except modules.ModuleError as e:
        await _set(svc, module_id, status="failed", error=str(e))
    except Exception as e:  # noqa: BLE001 — сбой разбора не должен ронять сервер
        log.exception("модуль %s не разобран", module_id)
        await _set(svc, module_id, status="failed", error=f"внутренняя ошибка: {e}"[:500])


async def translate(svc, module_id: str, text: str, note: str, packs_root: Path):
    """(черновик, предупреждения, ошибки): разбор книги моделью с проверкой сервера."""
    srd = await asyncio.to_thread(modules.srd, packs_root)
    async with svc.maker() as s:
        model, api_base = await _model(s)
    msgs = [
        {"role": "system", "content": modules.SYSTEM},
        {"role": "user", "content": modules.translator_input(text, srd, note)},
    ]
    draft, warnings, errors, calls = None, [], ["модель не сдала приключение"], []
    for _ in range(ATTEMPTS):
        call = LlmCall(campaign_id=None, purpose="module_import", model=model)
        calls.append(call)
        try:
            reply = await svc.llm.complete(
                msgs,
                model=model,
                tools=[modules.tool_spec()],
                tool_choice="required",
                max_tokens=MAX_TOKENS,
                temperature=0.2,  # перенос книги, а не сочинение
                api_base=api_base,
            )
        except LLMError as e:
            call.error = str(e)[:2000]
            errors = [f"модель недоступна: {e}"]
            break
        _log(call, reply)
        tc = next((t for t in reply.tool_calls if t.name == modules.TOOL), None)
        if tc is None:
            errors = [f"модель не вызвала {modules.TOOL}"]
            call.error = errors[0]
            msgs.append(reply.message or {"role": "assistant", "content": reply.text})
            msgs.append({"role": "user", "content": f"Сдай приключение вызовом {modules.TOOL}."})
            continue
        draft, errors, warnings = modules.check(tc.arguments, packs_root)
        if draft is not None:
            break
        call.error = "; ".join(errors)[:2000]
        msgs.append(_assistant(reply, tc))
        msgs.append(
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(
                    {"ok": False, "errors": errors, "hint": "исправь и сдай приключение целиком ещё раз"},
                    ensure_ascii=False,
                ),
            }
        )
    async with svc.maker() as s:
        s.add_all(calls)
        await s.commit()
    return draft, warnings, errors


async def run_maps(svc, module_id: str, media_dir: Path, only: str | None = None) -> None:
    """Номера комнат на картах. Карта, которую модель не разобрала, остаётся с ошибкой: админ отметит её сам."""
    try:
        async with svc.maker() as s:
            m = await s.get(AdventureModule, module_id)
            if m is None:
                return
            draft, maps = m.draft, [dict(x) for x in m.maps or []]
            model, api_base = await _model(s)
        base = folder(media_dir, module_id)
        for mp in maps:
            if only is not None and mp["id"] != only:
                continue
            taken = {x["location_id"]: x["id"] for x in maps if x.get("location_id") and x["id"] != mp["id"]}
            image = base / mp["file"]
            result, error = await read_map(svc, image, mp.get("mime", "image/png"), draft, taken, model, api_base)
            if result is not None:
                mp.update(result, status="ok", error=None)
            else:
                mp.update(status="failed", error=error)
        async with svc.maker() as s:
            m = await s.get(AdventureModule, module_id)
            if m is None:
                return
            done = {x["id"]: x for x in maps if only is None or x["id"] == only}
            # пока модель смотрела карты, админ мог добавить или удалить карту: список берём из базы
            m.maps = [done.get(x["id"], x) for x in m.maps or []]
            if m.status == "mapping":
                m.status = "review"
            await s.commit()
    except Exception as e:  # noqa: BLE001
        log.exception("карты модуля %s не разобраны", module_id)
        await _set(svc, module_id, status="review", error=f"карты не разобраны: {e}"[:500])


async def read_map(svc, path: Path, mime: str, draft: dict, taken: dict, model: str, api_base: str | None):
    """(место и отметки, None) или (None, причина)."""
    image = base64.b64encode(path.read_bytes()).decode()
    msgs = [
        {"role": "system", "content": modules.MAP_SYSTEM},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": modules.map_input(draft, taken)},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image}"}},
            ],
        },
    ]
    error, calls, result = "модель не отметила номера", [], None
    for _ in range(MAP_ATTEMPTS):
        call = LlmCall(campaign_id=None, purpose="module_map", model=model)
        calls.append(call)
        try:
            reply = await svc.llm.complete(
                msgs,
                model=model,
                tools=[modules.map_tool_spec()],
                tool_choice="required",
                max_tokens=MAP_TOKENS,
                temperature=0.0,
                api_base=api_base,
            )
        except LLMError as e:
            call.error = error = f"модель недоступна: {e}"[:2000]
            break
        _log(call, reply)
        tc = next((t for t in reply.tool_calls if t.name == modules.MAP_TOOL), None)
        if tc is None:
            call.error = error = f"модель не вызвала {modules.MAP_TOOL}"
            msgs.append(reply.message or {"role": "assistant", "content": reply.text})
            msgs.append({"role": "user", "content": f"Сдай ответ вызовом {modules.MAP_TOOL}."})
            continue
        result, errors = modules.check_marks(tc.arguments, draft)
        if result is not None:
            break
        call.error = error = "; ".join(errors)[:2000]
        msgs.append(_assistant(reply, tc))
        msgs.append(
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps({"ok": False, "errors": errors}, ensure_ascii=False),
            }
        )
    async with svc.maker() as s:
        s.add_all(calls)
        await s.commit()
    return (result, None) if result is not None else (None, error)
