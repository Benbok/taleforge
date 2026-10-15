"""Реестр инструментов мастера (ТЗ, разделы 3.1 и 7): Pydantic-схема + обработчик + права.

Описание для модели генерируется из схемы. Поля с id каждый ход получают список реально допустимых значений
(раздел 7.1, «динамические схемы»), поэтому выдуманную цель модель не может даже записать в вызов.
Ответ всегда ``{ok, result, event_id}`` или ``{ok: false, error}``; ошибка возвращается модели, и она исправляет вызов.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import CatalogError
from app.core.resolution.contracts import ActionProgress, ActionRef, FailureCategory, FailureInfo, ToolActionBinding
from app.core.world import World, WorldError, load_world
from app.db.models import Campaign, Entity, Event
from app.rules.dice import Dice, DiceError, DiceRoll
from app.rules.dnd5e.engine import RulesError

log = logging.getLogger(__name__)


class ToolError(Exception):
    """Отказ инструмента с причиной и, если есть, допустимыми вариантами. Уходит модели."""

    def __init__(self, message: str, *, code: str = "unclassified", category: FailureCategory = "unknown"):
        super().__init__(message)
        self.code = code
        self.category = category


class UnsupportedMechanicError(ToolError):
    """Server-confirmed absence of a supported mechanic, never an inferred error."""

    def __init__(self, message: str, *, code: str = "unsupported_mechanic"):
        super().__init__(message, code=code, category="unsupported")


def _failure(message: str, code: str, category: FailureCategory, key: str | None, *, rolled_back=False):
    return {
        "ok": False,
        "error": message,
        "failure": FailureInfo(
            code=code, category=category, rolled_back=rolled_back, attempt_id=key or ""
        ).model_dump(),
    }


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
    carded: set[str] = field(default_factory=set)  # события, у которых уже есть карточка броска в чате
    audio: list[dict[str, Any]] = field(default_factory=list)  # эффекты звука, прозвучат с публикацией хода
    sfx_requests: list[str] = field(default_factory=list)  # generated SFX reserve the shared per-turn budget
    generated_sfx_events: list[tuple[Any, str]] = field(default_factory=list)  # automatic per-action SFX specs
    saved_sfx: list[dict[str, Any]] = field(default_factory=list)
    # события клиентам после фиксации хода: (тип, данные, кому — места или None для всех)
    notices: list[tuple[str, dict[str, Any], list[str] | None]] = field(default_factory=list)
    call_key: str | None = None
    _first_event: Event | None = None
    resolved_actions: set[str] = field(default_factory=set)
    required_actions: list[ActionRef] = field(default_factory=list)
    action_progress: dict[str, ActionProgress] = field(default_factory=dict)
    current_binding: ToolActionBinding | None = None
    remaining_resolution_calls: int = 0
    resolution_calls_used: int = 0
    turn_diagnostics: dict = field(default_factory=dict)
    # подготовки мира, принятые вызовами этого хода: ход ждёт их перед повествованием (поставка 2)
    operation_refs: set[str] = field(default_factory=set)
    content_misses: set[tuple[str, str]] = field(default_factory=set)  # (вид, id) шаблонов, которых нет: invent_item
    # Actual narration audience can include heroes who joined the party during this turn.
    narration_viewer_ids: set[str] | None = None

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
        # Снимок карты фиксируется в тех же границах транзакции, что и событие.
        # Helper ничего не пишет в журнал и не вызывает record повторно.
        from app.core.layout.furnish import sync_objects
        from app.core.map_memory import observe_present

        inverse = inverse if inverse is not None else []
        changed = {key for key in (target_id, actor_id) if key in self.world.entities}
        rooms = set()
        for entity in self.session.dirty | self.session.new | self.session.deleted:
            if isinstance(entity, Entity) and entity.id:
                changed.add(entity.id)
                rooms.add(entity.location_id)
                rooms.update(inspect(entity).attrs.location_id.history.deleted)
        for entry in inverse:
            if entry.get("table") == "entities":
                key = entry.get("id") or (entry.get("row") or {}).get("id")
                if key:
                    changed.add(key)
                rooms.add((entry.get("row") or {}).get("location_id"))
                if entry.get("field") == "location_id":
                    rooms.add(entry.get("before"))
        sync_objects(self, inverse, changed=changed, rooms=rooms)
        await observe_present(self, inverse)
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
    internal: bool = False


ToolSpec = Tool


@dataclass
class InternalGrant:
    """Server-issued authorization required to execute internal tools."""

    campaign_id: str
    allowed_calls: tuple[tuple[str, str | None], ...]
    token: str = field(default_factory=lambda: secrets.token_hex(16))
    consumed: set[int] = field(default_factory=set)

    def consume(self, tool_name: str, key: str | None) -> bool:
        for idx, (t, k) in enumerate(self.allowed_calls):
            if idx in self.consumed:
                continue
            if t == tool_name and (k is None or k == key or _fit_key(k) == key):
                self.consumed.add(idx)
                return True
        return False


def issue_internal_grant(campaign_id: str, calls: tuple[Any, ...]) -> InternalGrant:
    """Issue a scoped single-group InternalGrant for compiled calls."""
    allowed = []
    for c in calls:
        tool_name = getattr(c, "tool", None) or (c.get("tool") if isinstance(c, dict) else str(c))
        call_key = getattr(c, "call_key", None) or (c.get("call_key") if isinstance(c, dict) else None)
        allowed.append((tool_name, call_key))
    return InternalGrant(campaign_id=campaign_id, allowed_calls=tuple(allowed))


REGISTRY: dict[str, Tool] = {}
# Правила, которые срабатывают сами после каждого изменяющего вызова (опыт за убитых врагов). Хук может дописать
# в результат вызова, что случилось; ошибка хука откатывает вызов целиком, как ошибка самого инструмента.
AFTER_CALL: list[Callable[[ToolContext, dict[str, Any]], Awaitable[None]]] = []


def tool(
    name: str,
    description: str,
    args: type[BaseModel],
    *,
    mutating: bool = True,
    ids=None,
    closes=True,
    internal: bool = False,
):
    def deco(fn: Handler) -> Handler:
        REGISTRY[name] = Tool(name, description, args, fn, mutating, dict(ids or {}), closes, internal)
        return fn

    return deco


def _enum_values(world: World, key: str) -> list[str]:
    if key == "dc":
        from app.core.adventure import book_refs

        return [e.id for e in world.catalog.dc_scale()] + book_refs(world)
    if key.startswith("templates:"):
        return [e.id for e in world.catalog.by_kind(key.split(":", 1)[1])]
    if key.startswith("plot:"):
        from app.core.plot import valid_ids

        return valid_ids(world.plot, key.split(":", 1)[1])
    if key.startswith("audio:"):
        from app.core import audio

        what = key.split(":", 1)[1]
        return [*audio.moods(world.campaign), "off"] if what == "moods" else audio.choices(world.campaign, what)
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
    if not t.internal and (
        t.mutating
        or t.closes_actions
        or t.name in {"cast_spell", "resolve_attack", "use_item", "roll_check"}
    ):
        props["action_ref"] = {
            "type": "object",
            "description": "Привязка к конкретной части заявки игрока",
            "properties": {
                "campaign_id": {"type": "string"},
                "source_kind": {"type": "string", "enum": ["message", "standing_response", "event"]},
                "source_id": {"type": "string"},
                "actor_id": {"type": "string"},
                "part": {"type": "integer", "minimum": 0},
            },
            "required": ["campaign_id", "source_kind", "source_id", "actor_id", "part"],
        }
    return schema


def tool_specs(world: World, names: list[str] | None = None) -> list[dict[str, Any]]:
    """Описания инструментов в формате function calling (OpenAI/LiteLLM)."""
    out = []
    for t in REGISTRY.values():
        if t.internal:
            continue
        if names is not None and t.name not in names:
            continue
        out.append(
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": schema_for(t, world)},
            }
        )
    return out


KEY_LEN = 64  # длина колонки events.idempotency_key


def _fit_key(key: str | None) -> str | None:
    """Длинный ключ (Gemini приклеивает к id вызова подпись мысли) сжимается в устойчивый хеш той же длины."""
    if key is None or len(key) <= KEY_LEN:
        return key
    return "h:" + hashlib.sha256(key.encode()).hexdigest()[: KEY_LEN - 2]


async def execute(
    ctx: ToolContext,
    name: str,
    raw_args: dict[str, Any] | None,
    key: str | None = None,
    *,
    grant: InternalGrant | None = None,
) -> dict:
    """Выполняет вызов. Повтор с тем же ключом идемпотентности возвращает прежний результат и ничего не меняет."""
    ctx.current_binding = None
    key = _fit_key(key)
    t = REGISTRY.get(name)
    if t is None:
        return _failure(f"нет инструмента {name}; доступны: {', '.join(REGISTRY)}", "unknown_tool", "unknown", key)
    raw_args = dict(raw_args or {})
    raw_action_ref = raw_args.pop("action_ref", None)
    explicit_ref = None
    if raw_action_ref is not None:
        try:
            explicit_ref = ActionRef.model_validate(raw_action_ref)
        except ValidationError as e:
            return _failure(f"неверный формат action_ref: {e}", "invalid_arguments", "invalid_arguments", key)
    if not t.internal:
        from app.agents.master.action_binding import bind_tool_action

        try:
            binding = await bind_tool_action(ctx, name, raw_args, explicit=explicit_ref)
        except ToolError as e:
            return _failure(str(e), e.code, e.category, key)
        ctx.current_binding = binding
    else:
        ctx.current_binding = None
    if t.internal:
        if grant is None:
            return _failure(
                f"инструмент {name} является внутренним и требует разрешения",
                "internal_tool_denied",
                "rule_denial",
                key,
            )
        if grant.campaign_id != ctx.campaign.id:
            return _failure(
                "граница кампании нарушена",
                "campaign_boundary_violation",
                "rule_denial",
                key,
            )
        if not grant.consume(name, key):
            return _failure(
                f"вызов {name} не авторизован выданным разрешением",
                "internal_tool_unauthorized",
                "rule_denial",
                key,
            )
    if ctx.current_binding is not None and key and t.mutating:
        from app.tools.resolution.context import refresh_world
        from app.tools.resolution.requests import lock_resolution_source

        await lock_resolution_source(ctx, ctx.current_binding.ref)
        await refresh_world(ctx)
    elif name == "roll_check" and key:
        from app.tools.resolution.context import refresh_world
        from app.tools.resolution.requests import bound_tool_key, lock_resolution_source

        refs = [ref for ref in ctx.required_actions if ref.actor_id == (raw_args or {}).get("character_id")]
        if refs and key == await bound_tool_key(ctx, name, raw_args or {}, "unbound_check"):
            # Serialize before reading the cached roll; a unique index alone
            # prevents duplicate storage but cannot prevent a second dice roll.
            for ref in sorted(refs, key=lambda ref: (ref.source_id, ref.part)):
                await lock_resolution_source(ctx, ref)
            await refresh_world(ctx)
    if key and t.mutating:
        q = select(Event).where(Event.campaign_id == ctx.campaign.id, Event.idempotency_key == key)
        prev = (await ctx.session.scalars(q)).first()
        if prev is not None:
            out = {
                "ok": True,
                "result": prev.payload.get("result", {}),
                "event_id": prev.id,
                "repeated": True,
                "tool": name,
            }
            ref = out["result"].get("operation_ref") if isinstance(out["result"], dict) else None
            if isinstance(ref, str):
                from app.core import preparation

                # квитанция неизменна, а статус — живой и идёт отдельным полем; Event.payload не меняется
                out["status"] = await preparation.brief_status(ctx.session, ctx.campaign.id, ref)
            from app.agents.master.action_progress import apply_tool_progress

            await apply_tool_progress(ctx, ctx.current_binding, out)
            return out
    try:
        args = t.args.model_validate(raw_args or {})
    except ValidationError as e:
        errs = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'аргументы'}: {x['msg']}" for x in e.errors())
        out = _failure(f"неверные аргументы: {errs}", "invalid_arguments", "invalid_arguments", key)
        from app.agents.master.action_progress import apply_tool_progress

        await apply_tool_progress(ctx, ctx.current_binding, out)
        return out
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
            out = _failure(
                f"{fname}: нет {', '.join(map(str, bad))} в сцене{hint}", "invalid_target", "rule_denial", key
            )
            from app.agents.master.action_progress import apply_tool_progress

            await apply_tool_progress(ctx, ctx.current_binding, out)
            return out
    from app.tools.resolution.context import restore_context, snapshot_context

    snapshot = snapshot_context(ctx)
    ctx.call_key = key
    ctx._first_event = None
    nested = await ctx.session.begin_nested()
    try:
        result = await t.handler(ctx, args)
        if t.mutating:
            for hook in AFTER_CALL:
                await hook(ctx, result)
    except (ToolError, WorldError, RulesError, DiceError, CatalogError) as e:
        await nested.rollback()
        # Откат точки сохранения сбрасывает изменённые объекты: перечитываем мир, чтобы следующий вызов видел БД
        await ctx.session.refresh(ctx.campaign)
        ctx.world = await load_world(ctx.session, ctx.campaign, ctx.world.catalog)
        restore_context(ctx, snapshot)
        if isinstance(e, CatalogError) and e.kind == "item_template" and e.rid:
            ctx.content_misses.add((e.kind, e.rid))
            log.warning("CONTENT_GAP campaign=%s turn=%s tool=%s missing=%s", ctx.campaign.id, ctx.turn_id, name, e.rid)
            out = _failure(
                f"{e}. Вне боя можно создать этот предмет через invent_item (missing_id={e.rid}) и повторить вызов",
                "missing_content",
                "rule_denial",
                key,
                rolled_back=True,
            )
        else:
            out = _failure(
                str(e),
                e.code if isinstance(e, ToolError) else "unclassified",
                e.category if isinstance(e, ToolError) else "unknown",
                key,
                rolled_back=True,
            )
        from app.agents.master.action_progress import apply_tool_progress

        await apply_tool_progress(ctx, ctx.current_binding, out)
        return out
    await nested.commit()
    ev = ctx._first_event
    if ev is not None:
        ev.payload = {**ev.payload, "result": result}
    if isinstance(result, dict) and isinstance(result.get("operation_ref"), str):
        ctx.operation_refs.add(result["operation_ref"])
    actors_to_close = []
    cid = getattr(args, "character_id", None)
    if t.closes_actions and cid:
        actors_to_close.append(cid)
    if t.closes_actions:
        for c in getattr(args, "character_ids", None) or []:
            actors_to_close.append(c)
    for f in ("attacker_id", "caster_id"):
        if t.closes_actions and getattr(args, f, None):
            actors_to_close.append(getattr(args, f))

    for a_id in actors_to_close:
        if any(r.actor_id == a_id for r in ctx.required_actions):
            from app.tools.resolution.requests import refresh_actor_closed

            refresh_actor_closed(ctx, a_id)
        else:
            ctx.closed.add(a_id)

    out = {"ok": True, "result": result, "event_id": ev.id if ev else None, "tool": name}
    if isinstance(result, dict) and isinstance(result.get("operation_ref"), str):
        from app.core import preparation

        # живой статус рядом с квитанцией, как у повтора по ключу: квитанция в Event.payload не меняется
        out["status"] = await preparation.brief_status(ctx.session, ctx.campaign.id, result["operation_ref"])

    from app.agents.master.action_progress import apply_tool_progress

    await apply_tool_progress(ctx, ctx.current_binding, out)
    return out


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
