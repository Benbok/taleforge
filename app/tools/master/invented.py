"""Предмет, которого нет в каталоге, мастер придумывает сам (спецификация 2026-10-13).

Только вне боя и только чтобы закрыть промах каталога этого хода. Механика — на языке модификаторов пакета,
в пределах обычного предмета SRD и только из операций, которые ``use_item`` действительно исполняет.
Запись ложится в пакет кампании (app/content/overlay.py) и в журнал пробелов контента.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.content import overlay
from app.content.loader import _core_validators
from app.core import adventure, combat
from app.rules.dice import DiceError, parse
from app.tools.registry import ToolContext, ToolError, tool

log = logging.getLogger(__name__)

MAX_PER_TURN = 2
MAX_PER_CAMPAIGN = 10
MAX_GIVE_QTY = 10
MAX_PRICE_CP = 5000  # 50 зм: дороже обычного предмета SRD не бывает
HEAL_AVG = 7  # как зелье лечения 2к4+2
HEAL_MAX = 10
TEMP_HP_MAX = 5
REMOVABLE = {"poisoned", "frightened"}


def _heal_errors(delta) -> list[str]:
    if isinstance(delta, bool):
        return ["лечение: delta — число или кубики"]
    if isinstance(delta, int):
        avg = top = delta
    elif isinstance(delta, str):
        try:
            expr = parse(delta)
        except DiceError:
            return [f"лечение: формула {delta!r} не читается"]
        dice = [t for t in expr.terms if not t.is_constant]
        if any(t.sign < 0 for t in dice):
            return ["лечение: кубики со знаком минус не допускаются"]
        avg = sum(t.count * (t.sides + 1) / 2 for t in dice) + expr.modifier
        top = sum(t.count * t.sides for t in dice) + expr.modifier
    else:
        return ["лечение: delta — число или кубики"]
    if avg <= 0:
        return ["лечение: только восстановление хитов, урон предмет не наносит"]
    if avg > HEAL_AVG or top > HEAL_MAX:
        return [f"лечение: в среднем не больше {HEAL_AVG} и не больше {HEAL_MAX} хитов, как зелье лечения 2к4+2"]
    return []


def power_errors(category: str, modifiers: list[dict]) -> list[str]:
    """Нарушения потолка силы; пустой список — запись допустима."""
    errors: list[str] = []
    if modifiers and category != "consumable":
        errors.append("механика бывает только у расходника (category: consumable): иначе предмет не тратится")
    for m in modifiers:
        op = m.get("op")
        if "if" in m or "triggers" in m:
            errors.append(f"{op}: условия и триггеры придуманному предмету недоступны")
        elif op == "resource" and m.get("stat") in ("hp", "stat.hp"):
            errors += _heal_errors(m.get("delta"))
        elif op == "add" and m.get("target") == "temp_hp":
            v = m.get("value")
            if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= TEMP_HP_MAX:
                errors.append(f"временных хитов — от 1 до {TEMP_HP_MAX}")
        elif op == "remove_condition":
            names = m.get("any_of") or [m.get("condition")]
            bad = [n for n in names if str(n or "").removeprefix("condition.") not in REMOVABLE]
            if bad or not names:
                errors.append(f"снять можно только {', '.join(sorted(REMOVABLE))}")
        else:
            errors.append(f"операция {op!r} недоступна: можно resource hp, add temp_hp, remove_condition")
    return errors


class InventItemArgs(BaseModel):
    missing_id: str = Field(pattern=r"^item\.[a-z0-9_]+$", description="id из ошибки missing_content этого хода")
    name: str = Field(min_length=1, max_length=80, description="название для игроков")
    description: str = Field(min_length=1, max_length=400, description="что это и что делает, видно игроку")
    category: Literal["consumable", "gear", "trinket"]
    modifiers: list[dict] = Field(default_factory=list, max_length=3, description="механика на языке пакета")
    weight: float = Field(0, ge=0, le=20)
    price_cp: int = Field(0, ge=0, le=MAX_PRICE_CP)
    reason: str = Field(min_length=1, max_length=300, description="зачем: «ягоды от заклинания Добрая ягода»")


def _ops_text(modifiers: list[dict]) -> str:
    parts = []
    for m in modifiers:
        bits = [str(m.get("op"))] + [str(m[k]) for k in ("stat", "target", "condition") if m.get(k)]
        bits += [str(m[k]) for k in ("delta", "value") if m.get(k) is not None]
        parts.append(":".join(bits))
    return ",".join(parts) or "-"


@tool(
    "invent_item",
    "Создаёт предмет, которого нет в каталоге, после ошибки missing_content в этом ходу. Только вне боя. "
    "Механика: resource hp (до 2к4+2), add temp_hp (до 5), remove_condition poisoned/frightened; "
    "механика только у consumable. Потом повтори исходный вызов с missing_id.",
    InventItemArgs,
    closes=False,
)
async def invent_item(ctx: ToolContext, a: InventItemArgs) -> dict:
    if combat.in_combat(ctx):
        raise ToolError("в бою недостающее не придумывается: откажи или реши иначе", code="invent_in_combat",
                        category="rule_denial")  # fmt: skip
    if adventure.is_module(ctx.campaign):
        raise ToolError("в готовом модуле канон книги: недостающий предмет не придумывается", code="invent_in_module",
                        category="rule_denial")  # fmt: skip
    if ("item_template", a.missing_id) not in ctx.content_misses:
        raise ToolError(f"в этом ходу не было промаха {a.missing_id}: придумывать можно только недостающее",
                        code="no_content_gap", category="rule_denial")  # fmt: skip
    made = [e for e in ctx.events if e.tool == "invent_item"]
    if len(made) >= MAX_PER_TURN:
        raise ToolError(f"не больше {MAX_PER_TURN} придуманных предметов за ход", code="invent_limit",
                        category="rule_denial")  # fmt: skip
    if len(await overlay.overlay_records(ctx.session, ctx.campaign)) >= MAX_PER_CAMPAIGN:
        raise ToolError(f"в кампании уже {MAX_PER_CAMPAIGN} придуманных предметов: дождись ревью владельца",
                        code="invent_limit", category="rule_denial")  # fmt: skip
    errors = power_errors(a.category, a.modifiers)
    record = {
        "id": a.missing_id,
        "name": a.name,
        "status": "proposal",
        "description": a.description,
        "category": a.category,
        "price": {"cp": a.price_cp},
        "weight": a.weight,
        "tags": ["invented"],
        "modifiers": a.modifiers,
    }
    validator = _core_validators().get("item_template")
    if validator is not None:
        errors += [f"{'/'.join(map(str, e.path)) or 'запись'}: {e.message}" for e in validator.iter_errors(record)]
    if errors:
        raise ToolError("; ".join(errors[:4]), code="invent_rejected", category="invalid_arguments")
    view = await overlay.add_record(ctx.session, ctx.campaign, "item_template", record)
    await ctx.record(
        "invent_item",
        payload={"missing_id": a.missing_id, "record": record, "reason": a.reason},
        hidden=True,
    )
    ctx.world.catalog = view
    log.warning(
        'CONTENT_GAP campaign=%s turn=%s missing=%s invented="%s" ops=%s',
        ctx.campaign.id, ctx.turn_id, a.missing_id, a.name, _ops_text(a.modifiers),
    )  # fmt: skip
    return {"item_template_id": a.missing_id, "name": a.name, "invented": True}
