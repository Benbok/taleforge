"""Расходы на модели для админки (этап 7, часть 6): итоги за период по дням, кампаниям, моделям и назначениям.

Admin видит свои кампании, Super Admin — все и ещё служебные вызовы вне кампаний (проверка моделей).
Лимит кампании считается за всё время, как его проверяет мастер (app/agents/master.py), а не за период.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Campaign, LlmCall, User, as_utc, now


def _add(bucket: dict[str, dict[str, Any]], key: str, c: LlmCall) -> None:
    b = bucket.setdefault(key, {"cost": 0.0, "calls": 0, "tokens_in": 0, "tokens_out": 0, "errors": 0})
    b["cost"] += c.cost or 0.0
    b["calls"] += 1
    b["tokens_in"] += c.tokens_in or 0
    b["tokens_out"] += c.tokens_out or 0
    b["errors"] += 1 if c.error else 0


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
    summary = total.get("all", {"cost": 0.0, "calls": 0, "tokens_in": 0, "tokens_out": 0, "errors": 0})
    return {
        "days": days,
        "scope": "all" if everything else "own",
        "total": {**summary, "cost": round(summary["cost"], 6)},
        "by_day": days_rows,
        "by_campaign": rows,
        "by_model": _rows(by_model, "model"),
        "by_purpose": _rows(by_purpose, "purpose"),
    }
