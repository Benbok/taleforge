"""Общая policy объектов мира (спецификация генерации сцен, §8.2): знание, видимость сейчас и доступ —
независимые решения.

- ``concealed`` — объект нельзя увидеть сейчас: тайный сам или тайная его деталь эскиза без явного обнаружения
  этим героем (``Knowledge.revealed_at``), тайный необнаруженный или закрытый контейнер-предок, неизвестный
  предок или цикл, объект уничтожен. Мастер видит всё — это решает вызывающий;
- память (``Knowledge``, ``KnownFact``, видимые прошлые сообщения) не делает объект видимым: карточка по памяти
  строится из сохранённого снимка наблюдения, без нынешнего описания, положения, количества и действий;
- доступ (``app/core/reach.py``) — видим, в той же комнате, все предки открыты, герой на клетке взаимодействия.

``observe`` пишет снимок наблюдения в разрешённых транзакциях (вход, раскрытие, открытие, перенос) только для
присутствующих героев, которым объект сейчас виден: закрытое и тайное побочно не раскрывается.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.world_objects import container_chain
from app.db.models import Knowledge

NOTHING: frozenset[str] = frozenset()


def _st(e: Any) -> dict:
    return e.state if isinstance(getattr(e, "state", None), dict) else {}


def hidden_feature(room: Any, entity_id: str) -> bool:
    """Деталь эскиза, привязанная к объекту, ещё не найдена героями."""
    sk = _st(room).get("sketch") if room is not None else None
    features = (sk or {}).get("features") or []
    return any(isinstance(f, dict) and f.get("entity_id") == entity_id and f.get("hidden") for f in features)


def _secret(obj: Any, entities: Mapping[str, Any]) -> bool:
    st = _st(obj)
    return bool(st.get("hidden") or st.get("secret")) or hidden_feature(entities.get(obj.location_id or ""), obj.id)


def concealed(entity: Any, entities: Mapping[str, Any], revealed: Iterable[str] = NOTHING) -> bool:
    """Объект нельзя увидеть прямо сейчас. ``revealed`` — что этот герой явно обнаружил."""
    if entity.kind == "location":
        return False  # тайные места открывает карта мест: посещение и знания (app/core/map.py)
    found = set(revealed)
    if entity.kind != "object":
        st = _st(entity)
        return bool(st.get("hidden") or st.get("secret")) and entity.id not in found
    if (_st(entity).get("world_object") or {}).get("physical") == "destroyed":
        return True
    try:
        chain = container_chain(entity, dict(entities))
    except ValueError:
        return True  # неизвестный родитель или цикл: доступа нет
    for obj in [entity, *chain]:
        if _secret(obj, entities) and obj.id not in found:
            return True
    return any(not (_st(parent).get("world_object") or {}).get("access", {}).get("open") for parent in chain)


async def revealed_to(session, hero_id: str | None) -> frozenset[str]:
    """Объекты, которые герой явно обнаружил."""
    if hero_id is None:
        return NOTHING
    q = select(Knowledge.entity_id).where(Knowledge.character_id == hero_id, Knowledge.revealed_at.is_not(None))
    return frozenset((await session.scalars(q)).all())


def snapshot(entity: Any) -> dict:
    return {
        "schema_version": 1,
        "name": entity.name,
        "description": entity.description or None,
        "observed_at": datetime.now(UTC).isoformat(),
    }


async def observe(ctx, place_id: str | None, inverse: list, *, only: Iterable[str] | None = None) -> None:
    """Присутствующие в месте герои запоминают видимые им сейчас объекты: снимок публичных полей.

    Строки знаний появляются уровнем 0 («видел»); уровень и ``revealed_at`` не меняются."""
    from app.core.world import PLAYABLE

    w = ctx.world
    if place_id is None:
        return
    heroes = [h for h in w.characters.values() if h.status in PLAYABLE and w.place_of(h) == place_id]
    wanted = set(only) if only is not None else None
    objects = [
        e
        for e in w.entities.values()
        if e.kind == "object"
        and e.location_id == place_id
        and (wanted is None or e.id in wanted)
        and not _st(e).get("area")
    ]
    if not heroes or not objects:
        return
    await ctx.session.flush()
    for hero in heroes:
        found = await revealed_to(ctx.session, hero.id)
        for e in objects:
            if concealed(e, w.entities, found):
                continue
            row = await ctx.session.get(Knowledge, (hero.id, e.id))
            seen = snapshot(e)
            if row is None:
                ctx.session.add(Knowledge(character_id=hero.id, entity_id=e.id, level=0, observed_snapshot=seen))
                inverse.append({"table": "knowledge", "op": "delete", "id": [hero.id, e.id]})
                continue
            old = row.observed_snapshot or {}
            if (old.get("name"), old.get("description")) == (seen["name"], seen["description"]):
                continue
            inverse.append(
                {
                    "table": "knowledge",
                    "id": [hero.id, e.id],
                    "field": "observed_snapshot",
                    "before": copy.deepcopy(row.observed_snapshot),
                }
            )
            row.observed_snapshot = seen
    await ctx.session.flush()
