"""Реестр инструментов мастера (ТЗ, разделы 3.1 и 7): Pydantic-схема + обработчик + права.

Описание для модели генерируется из схемы. Поля с id каждый ход получают список реально допустимых значений
(раздел 7.1, «динамические схемы»), поэтому выдуманную цель модель не может даже записать в вызов.
Ответ всегда ``{ok, result, event_id}`` или ``{ok: false, error}``; ошибка возвращается модели, и она исправляет вызов.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import CatalogError
from app.core.world import World, WorldError, load_world
from app.db.models import Campaign, Event
from app.rules.dice import Dice, DiceError, DiceRoll
from app.rules.dnd5e.engine import RulesError

log = logging.getLogger(__name__)


class ToolError(Exception):
    """Отказ инструмента с причиной и, если есть, допустимыми вариантами. Уходит модели."""


@dataclass
class ToolContext:
    session: AsyncSession
    campaign: Campaign
    world: World
    dice: Dice
    game_session_id: str | None
    turn_id: str | None
    actor_seat_id: str | None  # место мастера, от имени которого вызван инструмент
    events: list[Event] = field(default_factory=list)
    changed: set[str] = field(default_factory=set)  # id персонажей и сущностей, изменённых за ход
    outbox: list[dict[str, Any]] = field(default_factory=list)  # сообщения чата от инструментов (шёпот мастера)
    closed: set[str] = field(default_factory=set)  # персонажи, чьи действия закрыты вызовом или отказом
    signals: set[str] = field(default_factory=set)  # что сделать после фиксации хода (например, "replan")
    call_key: str | None = None
    _first_event: Event | None = None

    async def record(
        self,
        tool: str,
        *,
        actor_id: str | None = None,
        target_id: str | None = None,
        payload: dict[str, Any] | None = None,
        dice: list[Any] | None = None,
        inverse: list[Any] | None = None,
        hidden: bool = False,
    ) -> Event:
        ev = Event(
            campaign_id=self.campaign.id,
            session_id=self.game_session_id,
            turn_id=self.turn_id,
            tool=tool,
            actor_id=actor_id,
            target_id=target_id,
            payload=payload or {},
            dice=dice or [],
            inverse=inverse or [],
            hidden=hidden,
            game_time=self.world.scene.game_time,
            idempotency_key=self.call_key if self._first_event is None else None,
        )
        self.session.add(ev)
        await self.session.flush()
        if self._first_event is None:
            self._first_event = ev
        self.events.append(ev)
        for i in (actor_id, target_id):
            if i and (i in self.world.characters or i in self.world.entities):
                self.changed.add(i)
        return ev


Handler = Callable[[ToolContext, Any], Awaitable[dict[str, Any]]]


@dataclass
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Handler
    mutating: bool = True
    # поле → какой список допустимых id подставить в схему (ключ World.valid_ids или "dc", "templates:<kind>")
    id_fields: dict[str, str] = field(default_factory=dict)
    closes_actions: bool = True  # вызов с character_id закрывает действие этого персонажа (контракт намерения)


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, args: type[BaseModel], *, mutating: bool = True, ids=None, closes=True):
    def deco(fn: Handler) -> Handler:
        REGISTRY[name] = Tool(name, description, args, fn, mutating, dict(ids or {}), closes)
        return fn

    return deco


def _enum_values(world: World, key: str) -> list[str]:
    if key == "dc":
        return [e.id for e in world.catalog.dc_scale()]
    if key.startswith("templates:"):
        return [e.id for e in world.catalog.by_kind(key.split(":", 1)[1])]
    if key.startswith("plot:"):
        from app.core.plot import valid_ids

        return valid_ids(world.plot, key.split(":", 1)[1])
    if key == "seats":
        return [s.id for s in world.campaign.seats if s.role == "player" and s.occupant_type != "empty"]
    return world.valid_ids().get(key, [])


def schema_for(t: Tool, world: World) -> dict[str, Any]:
    """JSON-схема аргументов с перечнями допустимых id на этот ход. Длинные перечни шаблонов не подставляются:
    для них есть lookup_template, а сервер всё равно отклонит несуществующий id."""
    schema = copy.deepcopy(t.args.model_json_schema())
    schema.pop("title", None)
    props = schema.get("properties", {})
    for fname, key in t.id_fields.items():
        values = _enum_values(world, key)
        p = props.get(fname)
        if p is None or not values or len(values) > 60:
            continue
        if p.get("type") == "array":
            p["items"] = {"type": "string", "enum": values}
        else:
            p.pop("anyOf", None)
            p["type"] = "string"
            p["enum"] = values
    for p in props.values():
        p.pop("title", None)
    return schema


def tool_specs(world: World, names: list[str] | None = None) -> list[dict[str, Any]]:
    """Описания инструментов в формате function calling (OpenAI/LiteLLM)."""
    out = []
    for t in REGISTRY.values():
        if names is not None and t.name not in names:
            continue
        out.append(
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": schema_for(t, world)},
            }
        )
    return out


async def execute(ctx: ToolContext, name: str, raw_args: dict[str, Any] | None, key: str | None = None) -> dict:
    """Выполняет вызов. Повтор с тем же ключом идемпотентности возвращает прежний результат и ничего не меняет."""
    t = REGISTRY.get(name)
    if t is None:
        return {"ok": False, "error": f"нет инструмента {name}; доступны: {', '.join(REGISTRY)}"}
    if key and t.mutating:
        q = select(Event).where(Event.campaign_id == ctx.campaign.id, Event.idempotency_key == key)
        prev = (await ctx.session.scalars(q)).first()
        if prev is not None:
            return {"ok": True, "result": prev.payload.get("result", {}), "event_id": prev.id, "repeated": True}
    try:
        args = t.args.model_validate(raw_args or {})
    except ValidationError as e:
        errs = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'аргументы'}: {x['msg']}" for x in e.errors())
        return {"ok": False, "error": f"неверные аргументы: {errs}"}
    for fname, kind in t.id_fields.items():
        values = _enum_values(ctx.world, kind)
        val = getattr(args, fname, None)
        vals = val if isinstance(val, list) else [val]
        bad = [
            v
            for v in vals
            if v is not None
            and kind not in ("dc",)
            and not kind.startswith("templates:")
            and values is not None
            and v not in values
        ]
        if bad:
            hint = f"; допустимо: {', '.join(values[:30])}" if values else ""
            return {"ok": False, "error": f"{fname}: нет {', '.join(map(str, bad))} в сцене{hint}"}
    ctx.call_key = key
    ctx._first_event = None
    nested = await ctx.session.begin_nested()
    try:
        result = await t.handler(ctx, args)
    except (ToolError, WorldError, RulesError, DiceError, CatalogError) as e:
        await nested.rollback()
        # Откат точки сохранения сбрасывает изменённые объекты: перечитываем мир, чтобы следующий вызов видел БД
        await ctx.session.refresh(ctx.campaign)
        ctx.world = await load_world(ctx.session, ctx.campaign, ctx.world.catalog)
        ctx.events = [ev for ev in ctx.events if ev in ctx.session]
        return {"ok": False, "error": str(e)}
    await nested.commit()
    ev = ctx._first_event
    if ev is not None:
        ev.payload = {**ev.payload, "result": result}
    cid = getattr(args, "character_id", None)
    if t.closes_actions and cid:
        ctx.closed.add(cid)
    for cid in getattr(args, "character_ids", None) or []:
        ctx.closed.add(cid)
    if t.closes_actions and getattr(args, "attacker_id", None):
        ctx.closed.add(args.attacker_id)
    return {"ok": True, "result": result, "event_id": ev.id if ev else None}


def dice_json(roll: Any) -> dict[str, Any]:
    """Бросок для журнала: какие кубики и что выпало."""
    if isinstance(roll, DiceRoll):
        return {"expr": roll.text, "rolls": [list(r) for r in roll.rolls], "total": roll.total}
    return {
        "d20": list(roll.rolls),
        "natural": roll.natural,
        "modifier": roll.modifier,
        "mode": str(roll.mode),
        "total": roll.total,
    }
