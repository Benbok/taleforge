"""Предметы: инвентарь героев и вещи в сцене."""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from app.core import economy
from app.core import positions as grid
from app.core.world import is_scene_item
from app.db.models import Character, Entity, InventoryItem
from app.tools import effects as fx
from app.tools.master.base import (
    CELL_HINT,
    FOUND_ITEM,
    IMPROVISED_WEAPON,
    PLACE_HINT,
    Cell,
    Zone,
    _alive,
    _character,
    snapshot,
)
from app.tools.registry import ToolContext, ToolError, tool

# --- предметы ---


class UseItemArgs(BaseModel):
    character_id: str
    inventory_id: str
    target_id: str | None = Field(None, description="на кого применить; по умолчанию на себя")


@tool(
    "use_item",
    "Применяет предмет инвентаря по его шаблону (зелье, расходник). Свиток или формула творит записанное в нём "
    "заклинание по правилам cast_spell без ячейки. Оружие — через resolve_attack.",
    UseItemArgs,
    ids={"character_id": "characters", "inventory_id": "inventory", "target_id": "combatants"},
)
async def use_item(ctx: ToolContext, a: UseItemArgs) -> dict:
    ch = _character(ctx, a.character_id)
    it = next((i for i in ctx.world.inventory.get(ch.id, []) if i.id == a.inventory_id), None)
    if it is None:
        raise ToolError(f"у {ch.name} нет предмета {a.inventory_id}: рука нащупывает пустоту")
    if it.item_template_id == FOUND_ITEM:
        raise ToolError(f"«{ctx.world.item_name(it)}» — обычная вещь без механики: её применение реши проверкой")
    rec = ctx.world.catalog.get(it.item_template_id, "item_template")
    if rec.data.get("spell_scroll"):
        from app.tools.spells import read_scroll

        return await read_scroll(ctx, ch, it, rec, [a.target_id] if a.target_id else [])
    ops = rec.data.get("modifiers") or rec.data.get("use") or []
    if not ops:
        raise ToolError(f"у предмета {rec.name} нет механики применения")
    tgt = ctx.world.actor(a.target_id or ch.id)
    _alive(tgt, "Цель")
    inv = [snapshot(tgt), {"table": "inventory", "id": it.id, "field": "qty", "before": it.qty}]
    inv += economy.charge(ctx, ch.id, "use_object")
    out = await fx.run_ops(ctx, rec.id, ops, tgt, {})
    consumed = rec.data.get("category") == "consumable" or bool(rec.data.get("consumable"))
    if consumed:
        it.qty -= 1
        if it.qty <= 0:
            await ctx.session.delete(it)
            ctx.world.inventory[ch.id].remove(it)
    dice = out.pop("dice")
    result = {
        "user": ch.name,
        "item": ctx.world.item_name(it),
        "target": tgt.name,
        **out,
        "consumed": consumed,
        "target_status": ctx.world.actor(tgt.id).status(),
    }
    await ctx.record("use_item", actor_id=ch.id, target_id=tgt.id, payload=result, dice=dice, inverse=inv)
    return result


class GiveItemArgs(BaseModel):
    character_id: str
    item_template_id: str
    qty: int = Field(1, ge=1, le=100)
    display_name: str | None = Field(None, max_length=128, description="имя предмета в мире; свойства — из шаблона")
    reason: str = Field(description="откуда предмет: добыча, покупка, награда")


@tool(
    "give_item",
    "Выдаёт предмет из шаблона прямо в инвентарь персонажа: награда, покупка. Добычу, которая лежит в сцене, клади "
    "через place_item, а подбирает её герой (pick_up_item). Несуществующий шаблон — ошибка.",
    GiveItemArgs,
    ids={"character_id": "characters"},
)
async def give_item(ctx: ToolContext, a: GiveItemArgs) -> dict:
    ch = _character(ctx, a.character_id)
    rec = ctx.world.catalog.get(a.item_template_id, "item_template")
    inv_id, inverse = await _add_to_inventory(ctx, ch, rec.id, a.display_name, a.qty)
    result = {"character": ch.name, "item": a.display_name or rec.name, "qty": a.qty, "inventory_id": inv_id}
    await ctx.record(
        "give_item", target_id=ch.id, payload={**result, "reason": a.reason, "template": rec.id}, inverse=inverse
    )
    return result


class KeepFoundArgs(BaseModel):
    character_id: str
    name: str = Field(min_length=1, max_length=128, description="как вещь называется в мире: «арматура», «шляпа»")
    kind: Literal["object", "improvised_weapon", "template"] = Field(
        description="object — обычная вещь без механики (камень, шляпа, ключ); improvised_weapon — годится как "
        "оружие (арматура, ножка стула): импровизированное оружие SRD 1d4; template — есть подходящий шаблон пакета "
        "(украденный кинжал, найденное зелье), укажи item_template_id"
    )
    item_template_id: str | None = Field(None, description="только для kind=template")
    qty: int = Field(1, ge=1, le=100)
    from_id: str | None = Field(None, description="у кого или откуда взято: NPC, существо, объект сцены")
    how: Literal["found", "pried", "stolen", "looted", "given"] = Field(
        description="found — нашёл, pried — выломал или вытащил, stolen — украл, looted — снял с побеждённого, "
        "given — отдали"
    )
    reason: str = Field(min_length=1, max_length=300, description="что произошло, одной фразой")


HOW_RU = {"found": "находит", "pried": "добывает", "stolen": "крадёт", "looted": "забирает", "given": "получает"}


@tool(
    "keep_found_item",
    "Герой оставляет себе вещь, добытую в мире по ходу игры: нашёл камень, выломал арматуру из стены, украл шляпу "
    "у прохожего. Если добыть вещь было непросто (вытащить, украсть), сначала roll_check, и вызывай это только при "
    "успехе. Вещь попадает в инвентарь героя и остаётся там.",
    KeepFoundArgs,
    ids={"character_id": "characters", "from_id": "subjects"},
)
async def keep_found_item(ctx: ToolContext, a: KeepFoundArgs) -> dict:
    ch = _character(ctx, a.character_id)
    _can_handle(ctx, ch)
    if a.kind == "template":
        if not a.item_template_id:
            raise ToolError("для kind=template укажите item_template_id (найдите его через lookup_template)")
        template = ctx.world.catalog.get(a.item_template_id, "item_template").id
    elif a.item_template_id:
        raise ToolError("item_template_id — только для kind=template")
    elif a.kind == "improvised_weapon":
        template = ctx.world.catalog.get(IMPROVISED_WEAPON, "item_template").id
    else:
        template = FOUND_ITEM
    inv_id, inverse = await _add_to_inventory(ctx, ch, template, a.name, a.qty)
    src = ctx.world.entities.get(a.from_id or "") or ctx.world.characters.get(a.from_id or "")
    result = {"character": ch.name, "item": a.name, "qty": a.qty, "inventory_id": inv_id, "how": a.how}
    if src is not None:
        result["from"] = src.name
    await ctx.record(
        "keep_found_item",
        actor_id=ch.id,
        target_id=a.from_id if src is not None else None,
        payload={**result, "reason": a.reason, "template": template},
        inverse=inverse,
    )
    many = f" ×{a.qty}" if a.qty > 1 else ""
    ctx.outbox.append({"kind": "system", "content": f"{ch.name} {HOW_RU[a.how]} «{a.name}»{many}: вещь в инвентаре."})
    return result


async def _add_to_inventory(
    ctx: ToolContext, ch: Character, template_id: str, display_name: str | None, qty: int
) -> tuple[str, list[dict]]:
    """Кладёт предметы в инвентарь: такой же неснаряжённый предмет складывается в стопку. Строка инвентаря живёт в
    БД, поэтому подобранное остаётся у героя между ходами и сессиями. Возвращает id строки и обратную дельту."""
    items = ctx.world.inventory.setdefault(ch.id, [])
    same = next(
        (i for i in items if i.item_template_id == template_id and i.display_name == display_name and not i.equipped),
        None,
    )
    if same is not None:
        inverse = [{"table": "inventory", "id": same.id, "field": "qty", "before": same.qty}]
        same.qty += qty
        ctx.world.invalidate(ch.id)
        return same.id, inverse
    row = InventoryItem(character_id=ch.id, item_template_id=template_id, display_name=display_name, qty=qty)
    ctx.session.add(row)
    await ctx.session.flush()
    items.append(row)
    ctx.world.invalidate(ch.id)
    return row.id, [{"table": "inventory", "op": "delete", "id": row.id}]


async def _remove_from_inventory(ctx: ToolContext, ch: Character, it: InventoryItem, qty: int) -> list[dict]:
    if qty > it.qty:
        raise ToolError(f"у {ch.name} только {it.qty} шт. «{ctx.world.item_name(it)}»")
    inverse = [
        {
            "table": "inventory",
            "id": it.id,
            "field": "qty",
            "before": it.qty,
            "row": {
                "character_id": ch.id,
                "item_template_id": it.item_template_id,
                "display_name": it.display_name,
                "equipped": it.equipped,
            },
        }
    ]
    it.qty -= qty
    if it.qty == 0:
        await ctx.session.delete(it)
        ctx.world.inventory[ch.id].remove(it)
    ctx.world.invalidate(ch.id)
    return inverse


def _own_item(ctx: ToolContext, ch: Character, inventory_id: str) -> InventoryItem:
    it = next((i for i in ctx.world.inventory.get(ch.id, []) if i.id == inventory_id), None)
    if it is None:
        raise ToolError(f"у {ch.name} нет предмета {inventory_id}")
    return it


def _can_handle(ctx: ToolContext, ch: Character) -> None:
    act = ctx.world.actor(ch.id)
    if act.hp.current == 0:
        raise ToolError(f"{ch.name} без сознания: брать и отдавать вещи не может")


class TakeItemArgs(BaseModel):
    character_id: str
    inventory_id: str
    qty: int = Field(1, ge=1, le=100)
    reason: str


@tool(
    "take_item",
    "Забирает предмет из инвентаря персонажа.",
    TakeItemArgs,
    ids={"character_id": "characters", "inventory_id": "inventory"},
)
async def take_item(ctx: ToolContext, a: TakeItemArgs) -> dict:
    ch = _character(ctx, a.character_id)
    it = _own_item(ctx, ch, a.inventory_id)
    name = ctx.world.item_name(it)
    inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
    result = {"character": ch.name, "item": name, "qty": a.qty}
    await ctx.record("take_item", target_id=ch.id, payload={**result, "reason": a.reason}, inverse=inverse)
    return result


class EquipArgs(BaseModel):
    character_id: str
    inventory_id: str
    equipped: bool = True


@tool(
    "equip_item",
    "Надевает или снимает доспех, щит, берёт оружие в руки.",
    EquipArgs,
    ids={"character_id": "characters", "inventory_id": "inventory"},
)
async def equip_item(ctx: ToolContext, a: EquipArgs) -> dict:
    ch = _character(ctx, a.character_id)
    it = next((i for i in ctx.world.inventory.get(ch.id, []) if i.id == a.inventory_id), None)
    if it is None:
        raise ToolError(f"у {ch.name} нет предмета {a.inventory_id}")
    if it.item_template_id == FOUND_ITEM:
        raise ToolError(f"«{ctx.world.item_name(it)}» нельзя надеть или взять как оружие: это обычная вещь")
    rec = ctx.world.catalog.get(it.item_template_id, "item_template")
    inverse = [{"table": "inventory", "id": it.id, "field": "equipped", "before": it.equipped}]
    if a.equipped and rec.data.get("category") == "armor":
        kind = rec.data.get("armor_type")
        for other in ctx.world.inventory.get(ch.id, []):
            o = ctx.world.catalog.find(other.item_template_id)
            if other is not it and other.equipped and o and o.data.get("category") == "armor":
                if (o.data.get("armor_type") == "shield") == (kind == "shield"):
                    inverse.append({"table": "inventory", "id": other.id, "field": "equipped", "before": True})
                    other.equipped = False
    it.equipped = a.equipped
    ctx.world.invalidate(ch.id)
    act = ctx.world.actor(ch.id)
    result = {"character": ch.name, "item": ctx.world.item_name(it), "equipped": a.equipped, "ac": act.ac}
    await ctx.record("equip_item", target_id=ch.id, payload=result, inverse=inverse)
    return result


# --- предметы в сцене: добыча, которую герои подбирают сами ---


class PlaceItemArgs(BaseModel):
    item_template_id: str
    qty: int = Field(1, ge=1, le=100)
    display_name: str | None = Field(None, max_length=128, description="имя предмета в мире; свойства — из шаблона")
    zone: Zone = "near"
    cell: Cell | None = Field(None, description=CELL_HINT + "; можно на предмет эскиза (в сене, на столе), не в стену")
    description: str = Field(
        "", max_length=500, description="где и как лежит, как его видят герои: текст карточки для игроков"
    )
    reason: str = Field(description="откуда предмет: выпал у врага, лежит в сундуке, тайник")
    location_id: str | None = Field(None, description=PLACE_HINT)


@tool(
    "place_item",
    "Кладёт предмет из шаблона в текущую сцену: добыча у павшего врага, содержимое сундука, находка на полу. Герой "
    "подбирает его сам через pick_up_item, и тогда предмет остаётся в его инвентаре.",
    PlaceItemArgs,
    ids={"item_template_id": "templates:item_template", "location_id": "places"},
    closes=False,
)
async def place_item(ctx: ToolContext, a: PlaceItemArgs) -> dict:
    rec = ctx.world.catalog.get(a.item_template_id, "item_template")
    place = ctx.world.place_arg(a.location_id, "лежит предмет")
    cell = _floor(ctx, place or ctx.world.home(), a.cell)
    en, inverse = await _put_in_scene(ctx, rec.id, a.display_name, a.qty, a.zone, a.description, place, cell)
    result = {"entity_id": en.id, "item": en.name, "qty": a.qty}
    if a.cell is not None:
        result["cell"] = list(a.cell)
    await ctx.record(
        "place_item", target_id=en.id, payload={**result, "reason": a.reason, "template": rec.id}, inverse=inverse
    )
    return result


async def _put_in_scene(
    ctx: ToolContext,
    template_id: str,
    display_name: str | None,
    qty: int,
    zone: str,
    description: str = "",
    place: str | None = None,
    cell: tuple[int, int] | None = None,
) -> tuple[Entity, list[dict]]:
    """Предмет в сцене — объект реестра с шаблоном предмета. Такой же, что уже лежит там же, складывается в стопку.
    ``place`` — место, где он ляжет; по умолчанию основное место сцены. ``cell`` — точная клетка (от строя)."""
    rec = ctx.world.catalog.find(template_id, "item_template")
    name = display_name or (rec.name if rec else template_id)
    # Внешний вид задаёт шаблон, не имя вещи и не LLM; неизвестный клиенту ключ
    # безопасно отображается стандартным пресетом предмета.
    key = rec.data.get("visual_key") if rec else None
    visual_key = key if isinstance(key, str) and key else None
    place = place or ctx.world.home()
    for en in ctx.world.in_scene_entities(place):
        st = en.state or {}
        here = grid.pos_of(ctx.world, en.id).cell == cell if cell is not None else en.zone == zone and "cell" not in st
        same = en.template_id == template_id and st.get("display_name") == display_name and here
        if is_scene_item(en) and same:
            # Прежние стопки без визуального ключа получают его при пополнении.
            # Явный ключ уже существующего объекта не перезаписываем.
            visual = {"visual_key": visual_key} if visual_key and "visual_key" not in st else {}
            en.state = {**st, "qty": int(st.get("qty") or 1) + qty, **visual}
            return en, [{"table": "entities", "id": en.id, "field": "state", "before": st}]
    en = Entity(
        campaign_id=ctx.campaign.id,
        kind="object",
        name=name,
        template_id=template_id,
        description=description or ((rec.data.get("description") or "") if rec else ""),
        state={
            "item": True,
            "qty": qty,
            "display_name": display_name,
            **({"visual_key": visual_key} if visual_key is not None else {}),
        },
        location_id=place,
        zone=zone,
    )
    ctx.session.add(en)
    await ctx.session.flush()
    ctx.world.entities[en.id] = en
    if cell is not None:
        grid.set_cell(ctx.world, en.id, cell)
    return en, [{"table": "entities", "op": "delete", "id": en.id}]


def _floor(ctx: ToolContext, place: str | None, cell: list[int] | None) -> tuple[int, int] | None:
    """Клетка мастера → клетка от строя, с проверкой, что вещь там может лежать."""
    if cell is None:
        return None
    rel = grid.to_rel(ctx.world, place, cell)
    problem = grid.floor_problem(ctx.world, place, rel)
    if problem:
        raise ToolError(problem)
    return rel


class PickUpArgs(BaseModel):
    character_id: str
    entity_id: str = Field(description="предмет, который лежит в сцене")
    qty: int | None = Field(None, ge=1, le=100, description="сколько взять; по умолчанию всё")


@tool(
    "pick_up_item",
    "Герой подбирает предмет, лежащий в сцене: предмет переходит в его инвентарь и остаётся там. Бросок не нужен, "
    "если предмет никто не охраняет.",
    PickUpArgs,
    ids={"character_id": "characters", "entity_id": "scene_items"},
)
async def pick_up_item(ctx: ToolContext, a: PickUpArgs) -> dict:
    ch = _character(ctx, a.character_id)
    _can_handle(ctx, ch)
    en = ctx.world.entities.get(a.entity_id)
    if en is None or en not in ctx.world.in_scene_entities(ctx.world.place_of(ch)):
        raise ToolError(f"предмета {a.entity_id} нет рядом с {ch.name}")
    if not is_scene_item(en):
        raise ToolError(f"{en.name} — не предмет: его нельзя положить в инвентарь")
    st = dict(en.state or {})
    have = int(st.get("qty") or 1)
    qty = a.qty or have
    if qty > have:
        raise ToolError(f"здесь лежит только {have} шт. «{en.name}»")
    if en.template_id != FOUND_ITEM:
        ctx.world.catalog.get(en.template_id or "", "item_template")  # шаблон пропал из пакета — брать нечего
    inverse = [{"table": "entities", "op": "restore", "row": _entity_row(en)}]
    inv_id, inv = await _add_to_inventory(ctx, ch, en.template_id, st.get("display_name"), qty)
    inverse += inv
    result = {"character": ch.name, "item": en.name, "qty": qty, "inventory_id": inv_id, "left": have - qty}
    await ctx.record("pick_up_item", actor_id=ch.id, target_id=en.id, payload=result, inverse=inverse)
    many = f" ×{qty}" if qty > 1 else ""
    ctx.outbox.append({"kind": "system", "content": f"{ch.name} подбирает «{en.name}»{many}: предмет в инвентаре."})
    if qty == have:
        await ctx.session.delete(en)
        ctx.world.entities.pop(en.id, None)
    else:
        en.state = {**st, "qty": have - qty}
    return result


def _entity_row(en: Entity) -> dict:
    return {
        "id": en.id,
        "kind": en.kind,
        "name": en.name,
        "template_id": en.template_id,
        "description": en.description,
        "state": copy.deepcopy(en.state),
        "location_id": en.location_id,
        "zone": en.zone,
    }


class DropArgs(BaseModel):
    character_id: str
    inventory_id: str
    qty: int = Field(1, ge=1, le=100)


@tool(
    "drop_item",
    "Герой бросает или оставляет предмет из инвентаря в сцене: он ляжет рядом, и его можно будет подобрать снова.",
    DropArgs,
    ids={"character_id": "characters", "inventory_id": "inventory"},
)
async def drop_item(ctx: ToolContext, a: DropArgs) -> dict:
    ch = _character(ctx, a.character_id)
    it = _own_item(ctx, ch, a.inventory_id)
    template, display = it.item_template_id, it.display_name
    name = ctx.world.item_name(it)
    inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
    where = grid.pos_of(ctx.world, ch.id).cell  # герой на клетке — вещь ложится у его ног
    en, inv = await _put_in_scene(ctx, template, display, a.qty, "melee", place=ctx.world.place_of(ch), cell=where)
    inverse += inv
    result = {"character": ch.name, "item": name, "qty": a.qty, "entity_id": en.id}
    await ctx.record("drop_item", actor_id=ch.id, target_id=en.id, payload=result, inverse=inverse)
    return result


class PassItemArgs(BaseModel):
    character_id: str = Field(description="кто отдаёт")
    to_character_id: str = Field(description="кому из героев отряда")
    inventory_id: str
    qty: int = Field(1, ge=1, le=100)


@tool(
    "pass_item",
    "Герой передаёт предмет из своего инвентаря другому герою отряда.",
    PassItemArgs,
    ids={"character_id": "characters", "to_character_id": "characters", "inventory_id": "inventory"},
)
async def pass_item(ctx: ToolContext, a: PassItemArgs) -> dict:
    ch = _character(ctx, a.character_id)
    to = _character(ctx, a.to_character_id)
    if ch.id == to.id:
        raise ToolError("отдать предмет самому себе нельзя")
    _can_handle(ctx, ch)
    it = _own_item(ctx, ch, a.inventory_id)
    template, display = it.item_template_id, it.display_name
    name = ctx.world.item_name(it)
    inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
    inv_id, inv = await _add_to_inventory(ctx, to, template, display, a.qty)
    result = {"from": ch.name, "to": to.name, "item": name, "qty": a.qty, "inventory_id": inv_id}
    await ctx.record("pass_item", actor_id=ch.id, target_id=to.id, payload=result, inverse=inverse + inv)
    ctx.outbox.append(
        {"kind": "system", "content": f"{ch.name} передаёт {to.name} «{name}»{f' ×{a.qty}' if a.qty > 1 else ''}."}
    )
    return result
