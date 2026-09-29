"""Журнал мастера для администраторов: что мастер вызывал, с какими бросками и результатами, во что обошлись
обращения к модели. Короткий: без промптов и ответов модели, результаты — только простые поля.

Секретное (скрытые броски, шёпот одному игроку) помечается ``secret``. Показывать ли его содержимое, решает
одна функция ``secrets_visible``; при выключенной настройке от записи остаются только инструмент и пометка.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Event, LlmCall, MasterTurn
from app.tools.registry import REGISTRY

SECRET_TOOLS = {"whisper"}  # вызов секретен сам по себе, независимо от результата
TEXT_LIMIT = 160


def secrets_visible(settings: Settings) -> bool:
    return settings.master_log_secrets


def _short(v: Any) -> Any:
    return v[:TEXT_LIMIT] + "…" if isinstance(v, str) and len(v) > TEXT_LIMIT else v


def _scalars(d: Any) -> dict[str, Any]:
    """Только простые поля: вложенные структуры (листы, шаблоны, лор) в короткий журнал не попадают."""
    if not isinstance(d, dict):
        return {}
    return {k: _short(v) for k, v in d.items() if isinstance(v, str | int | float | bool) or v is None}


def _call(raw: dict[str, Any], hidden_events: set[str]) -> dict[str, Any]:
    name = raw.get("tool", "?")
    res = raw.get("result") or {}
    inner = res.get("result") if isinstance(res.get("result"), dict) else {}
    secret = name in SECRET_TOOLS or bool(inner.get("hidden")) or res.get("event_id") in hidden_events
    t = REGISTRY.get(name)
    out: dict[str, Any] = {"tool": name, "secret": secret, "ok": bool(res.get("ok")), "args": _scalars(raw.get("args"))}
    if res.get("error"):
        out["error"] = _short(res["error"])
    if t is None or t.mutating:  # у читающих инструментов (сцена, лист, шаблон) результат — справка, не событие
        out["result"] = _scalars(inner)
    for k in ("routed", "auto"):
        if raw.get(k):
            out[k] = True
    return out


def _llm(c: LlmCall) -> dict[str, Any]:
    return {
        "purpose": c.purpose,
        "model": c.model,
        "tokens_in": c.tokens_in,
        "tokens_out": c.tokens_out,
        "cost": c.cost,
        "latency_ms": c.latency_ms,
        "error": _short(c.error),
        "at": c.created_at,
    }


def redact(call: dict[str, Any]) -> dict[str, Any]:
    return {"tool": call["tool"], "secret": True}


async def build(s: AsyncSession, campaign_id: str, settings: Settings, limit: int = 30) -> dict[str, Any]:
    """Последние ``limit`` ходов мастера, новые сверху, и служебные вызовы модели вне ходов."""
    turns = (
        await s.scalars(
            select(MasterTurn)
            .where(MasterTurn.campaign_id == campaign_id)
            .order_by(MasterTurn.started_at.desc())
            .limit(limit)
        )
    ).all()
    ids = [t.id for t in turns]
    hidden = set(
        (await s.scalars(select(Event.id).where(Event.turn_id.in_(ids), Event.hidden.is_(True)))).all() if ids else []
    )
    llm_by_turn: dict[str, list[dict]] = {}
    if ids:
        for c in await s.scalars(select(LlmCall).where(LlmCall.turn_id.in_(ids)).order_by(LlmCall.created_at)):
            llm_by_turn.setdefault(c.turn_id, []).append(_llm(c))
    service = (
        await s.scalars(
            select(LlmCall)
            .where(LlmCall.campaign_id == campaign_id, LlmCall.turn_id.is_(None))
            .order_by(LlmCall.created_at.desc())
            .limit(limit)
        )
    ).all()

    show = secrets_visible(settings)
    out = []
    for t in turns:
        tr = t.trace or {}
        calls = [_call(c, hidden) for c in tr.get("calls") or []]
        out.append(
            {
                "id": t.id,
                "session_id": t.session_id,
                "status": t.status,
                "started_at": t.started_at,
                "finished_at": t.finished_at,
                "seq": [tr.get("from_seq"), t.upto_seq],
                "calls": [c if show or not c["secret"] else redact(c) for c in calls],
                "combat": tr.get("combat") or [],
                "advance": tr.get("advance"),
                "audit": tr.get("audit"),
                "error": _short(tr.get("error")),
                "llm": llm_by_turn.get(t.id, []),
            }
        )
    # живой мастер ходит вне ходов ИИ: его вызовы — события журнала без хода
    live = (
        await s.scalars(
            select(Event)
            .where(Event.campaign_id == campaign_id, Event.turn_id.is_(None))
            .order_by(Event.created_at.desc())
            .limit(limit)
        )
    ).all()
    manual = []
    for e in live:
        row = {"tool": e.tool, "at": e.created_at, "secret": e.hidden or e.tool in SECRET_TOOLS}
        if show or not row["secret"]:
            row["result"] = _scalars((e.payload or {}).get("result"))
        manual.append(row)
    return {"secrets_visible": show, "turns": out, "service_llm": [_llm(c) for c in service], "live": manual}
