"""Расходы на модели для админки (этап 7, часть 6): итоги за период по дням, кампаниям, моделям и назначениям.

Admin видит свои кампании, Super Admin — все и ещё служебные вызовы вне кампаний (проверка моделей).
Лимит кампании считается за всё время, как его проверяет мастер (app/agents/master.py), а не за период.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, LlmCall, User, as_utc, now


def _add(bucket: dict[str, dict[str, Any]], key: str, c: LlmCall) -> None:
    b = bucket.setdefault(
        key,
        {"cost": 0.0, "calls": 0, "tokens_in": 0, "tokens_out": 0, "tokens_reasoning": 0, "errors": 0},
    )
    b["cost"] += c.cost or 0.0
    b["calls"] += 1
    b["tokens_in"] += c.tokens_in or 0
    b["tokens_out"] += c.tokens_out or 0
    b["tokens_reasoning"] += c.tokens_reasoning or 0
    b["errors"] += 1 if c.error else 0
    known_cost = getattr(c, "cost_known", None) is True
    cached = getattr(c, "tokens_cached", None)
    for field, value in {
        "cost_known_calls": int(known_cost),
        "cost_unknown_calls": int(not known_cost),
        "cache_known_calls": int(cached is not None),
        "cache_unknown_calls": int(cached is None),
        "tokens_cached_known": cached or 0,
        "tokens_uncached_known": max(0, (c.tokens_in or 0) - cached) if cached is not None else 0,
    }.items():
        b[field] = b.get(field, 0) + value


def session_report(calls: list[LlmCall], turns: list) -> dict[str, Any]:
    """All paid attempts survive aggregation, including invalid output and rolled back turns."""
    total, by_purpose, by_phase = {}, {}, {}
    creation = {"plan", "sketch", "scene", "layout", "campaign_intro", "greeting", "intro"}
    for call in calls:
        _add(total, "all", call)
        _add(by_purpose, call.purpose, call)
        phase = "turn" if call.turn_id else "creation" if call.purpose in creation else "unattributed"
        _add(by_phase, phase, call)
    done = [t for t in turns if t.status == "done"]
    failed = [t for t in turns if t.status == "failed"]
    decisions = Counter(c.turn_id for c in calls if c.purpose == "decide" and c.turn_id)

    def durations(rows):
        values = sorted(
            (as_utc(t.finished_at) - as_utc(t.started_at)).total_seconds() * 1000
            for t in rows
            if t.finished_at and t.started_at
        )

        def percentile(p):
            if not values:
                return None
            pos = (len(values) - 1) * p
            lo = int(pos)
            return round(values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (pos - lo), 2)

        return {"count": len(values), "p50": percentile(0.5), "p95": percentile(0.95)}

    summary = total.get("all", {"cost": 0, "calls": 0})
    summary = {**summary, "cost": round(summary["cost"], 6)}
    for prefix in ("cache", "cost"):
        summary[f"{prefix}_coverage"] = summary.get(f"{prefix}_known_calls", 0) / len(calls) if calls else None
    return {
        "total": summary,
        "by_purpose": {r["purpose"]: r for r in _rows(by_purpose, "purpose")},
        "by_phase": {r["phase"]: r for r in _rows(by_phase, "phase")},
        "done_turns": len(done),
        "failed_turns": len(failed),
        "other_turns": len(turns) - len(done) - len(failed),
        "unattributed_calls": sum(not c.turn_id for c in calls),
        "mean_decide_done": sum(decisions[t.id] for t in done) / len(done) if done else None,
        "mean_decide_all": sum(decisions[t.id] for t in turns) / len(turns) if turns else None,
        "duration_ms": {"done": durations(done), "failed": durations(failed), "all": durations(turns)},
    }


def _rows(bucket: dict[str, dict[str, Any]], name: str) -> list[dict[str, Any]]:
    out = [{name: k, **v, "cost": round(v["cost"], 6)} for k, v in bucket.items()]
    return sorted(out, key=lambda r: -r["cost"])


async def report(s: AsyncSession, user: User, days: int) -> dict[str, Any]:
    everything = user.platform_role == "super_admin"
    q = select(Campaign.id, Campaign.name, Campaign.settings)
    if not everything:
        q = q.where(Campaign.owner_id == user.id)
    campaigns = {cid: (name, settings or {}) for cid, name, settings in (await s.execute(q)).all()}

    since = now() - timedelta(days=days)
    ids = list(campaigns)
    calls = select(LlmCall).where(LlmCall.created_at >= since)
    if not everything:
        calls = calls.where(LlmCall.campaign_id.in_(ids))  # пустой список — пустой отчёт

    total: dict[str, dict[str, Any]] = {}
    by_day: dict[str, dict[str, Any]] = {}
    by_campaign: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_purpose: dict[str, dict[str, Any]] = {}
    for c in await s.scalars(calls):
        _add(total, "all", c)
        _add(by_day, as_utc(c.created_at).date().isoformat(), c)
        _add(by_campaign, c.campaign_id or "", c)
        _add(by_model, c.model, c)
        _add(by_purpose, c.purpose, c)

    # лимит — против расходов за всё время
    lifetime: dict[str, float] = defaultdict(float)
    if ids:
        q = select(LlmCall.campaign_id, func.sum(LlmCall.cost)).where(LlmCall.campaign_id.in_(ids))
        for cid, cost in (await s.execute(q.group_by(LlmCall.campaign_id))).all():
            lifetime[cid] = float(cost or 0.0)

    rows = []
    for r in _rows(by_campaign, "id"):
        name, settings = campaigns.get(r["id"], (None, {}))
        limit = settings.get("spend_limit_usd")
        rows.append(
            {
                **r,
                "name": name if r["id"] else "Вне кампаний: проверка моделей и разбор приключений",
                "limit": limit,
                "spent_total": round(lifetime.get(r["id"], 0.0), 6),
            }
        )
    days_rows = sorted(_rows(by_day, "day"), key=lambda r: r["day"])
    summary = total.get(
        "all",
        {"cost": 0.0, "calls": 0, "tokens_in": 0, "tokens_out": 0, "tokens_reasoning": 0, "errors": 0},
    )
    return {
        "days": days,
        "scope": "all" if everything else "own",
        "total": {**summary, "cost": round(summary["cost"], 6)},
        "by_day": days_rows,
        "by_campaign": rows,
        "by_model": _rows(by_model, "model"),
        "by_purpose": _rows(by_purpose, "purpose"),
    }
