"""Пробелы контента: предметы, которые мастер придумал в игре, — готовым YAML для пакета.

    uv run python tools/content_gaps.py c_d45c8e2b5c660e33
    uv run python tools/content_gaps.py --all

Перенос в пакет — решение владельца: поменять status на canon, поправить механику или выбросить запись.
"""

from __future__ import annotations

import argparse
import asyncio

import yaml
from sqlalchemy import select

from app.db.models import Event


async def collect(session, campaign_id: str | None) -> list[dict]:
    q = select(Event).where(Event.tool == "invent_item")
    if campaign_id:
        q = q.where(Event.campaign_id == campaign_id)
    rows = (await session.scalars(q.order_by(Event.created_at))).all()
    return [
        {
            "campaign_id": e.campaign_id,
            "missing_id": e.payload["missing_id"],
            "record": e.payload["record"],
            "reason": e.payload.get("reason", ""),
            "created_at": e.created_at.isoformat() if e.created_at else "",
        }
        for e in rows
    ]


def to_yaml(items: list[dict]) -> str:
    latest = {i["missing_id"]: i["record"] for i in items}  # последняя версия записи на id
    return yaml.safe_dump({"kind": "item_template", "items": list(latest.values())}, allow_unicode=True,
                          sort_keys=False)  # fmt: skip


async def _main(campaign_id: str | None) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import Settings

    engine = create_async_engine(Settings.from_env().database_url)
    async with async_sessionmaker(engine)() as s:
        items = await collect(s, campaign_id)
    for i in items:
        print(f"# {i['created_at']} {i['campaign_id']} {i['missing_id']}: {i['reason']}")
    print(to_yaml(items))
    await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("campaign_id", nargs="?")
    p.add_argument("--all", action="store_true")
    a = p.parse_args()
    asyncio.run(_main(None if a.all else a.campaign_id))
