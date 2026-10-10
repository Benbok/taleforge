"""Предметы: инвентарь героев и вещи в сцене."""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from app.core import economy
from app.core import positions as grid
from app.core.world import is_scene_item
from app.core.world_objects import container_chain, container_parent, is_nested, read_world_object
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
            if it.world_entity_id is not None:
                entity = _unique_inventory_entity(ctx, it)
                inv.append(
                    {"table": "entities", "id": entity.id, "field": "state", "before": copy.deepcopy(entity.state)}
                )
                entity.state = _object_state(entity, physical="destroyed")
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
    unique = bool(rec.data.get("unique"))
    if unique and a.qty != 1:
        raise ToolError("уникальный экземпляр нельзя выдавать стопкой")
    entity = await _new_unique_item(ctx, rec.id, a.display_name) if unique else None
    inv_id, inverse = await _add_to_inventory(
        ctx, ch, rec.id, a.display_name, a.qty, world_entity_id=entity.id if entity else None
    )
    if entity is not None:
        inverse.append({"table": "entities", "op": "delete", "id": entity.id})
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


def _world_item_state() -> dict:
    return {
        "schema_version": 1,
        "role": "item",
        "capabilities": ["inspect", "take", "put"],
        "unique": True,
        "container_id": None,
        "revision": 0,
        "physical": "intact",
    }


def _object_state(entity: Entity, **changes: object) -> dict:
    previous = dict((entity.state or {}).get("world_object") or {})
    world_object = {**previous, **changes, "revision": int(previous.get("revision", 0)) + 1}
    return {**(entity.state or {}), "world_object": world_object}


async def _new_unique_item(ctx: ToolContext, template_id: str, display_name: str | None) -> Entity:
    rec = ctx.world.catalog.get(template_id, "item_template")
    key = rec.data.get("visual_key")
    entity = Entity(
        campaign_id=ctx.campaign.id,
        kind="object",
        template_id=template_id,
        name=display_name or rec.name,
        description=rec.data.get("description") or "",
        location_id=None,
        state={
            "item": True,
            "qty": 1,
            "display_name": display_name,
            "world_object": _world_item_state(),
            **({"visual_key": key} if isinstance(key, str) else {}),
        },
    )
    ctx.session.add(entity)
    await ctx.session.flush()
    ctx.world.entities[entity.id] = entity
    return entity


def _unique_inventory_entity(ctx: ToolContext, item: InventoryItem) -> Entity:
    entity = ctx.world.entities.get(item.world_entity_id or "")
    if entity is None or entity.campaign_id != ctx.campaign.id or not read_world_object(entity).unique:
        raise ToolError("уникальный предмет не найден в текущей кампании")
    if entity.location_id is not None or is_nested(entity):
        raise ToolError("уникальный предмет уже размещён в мире")
    return entity


async def _add_to_inventory(
    ctx: ToolContext,
    ch: Character,
    template_id: str,
    display_name: str | None,
    qty: int,
    *,
    world_entity_id: str | None = None,
) -> tuple[str, list[dict]]:
    """Кладёт предметы в инвентарь: такой же неснаряжённый предмет складывается в стопку. Строка инвентаря живёт в
    БД, поэтому подобранное остаётся у героя между ходами и сессиями. Возвращает id строки и обратную дельту."""
    items = ctx.world.inventory.setdefault(ch.id, [])
    if world_entity_id is not None and qty != 1:
        raise ToolError("уникальный предмет не может быть стопкой")
    same = next(
        (
            i
            for i in items
            if world_entity_id is None
            and i.world_entity_id is None
            and i.item_template_id == template_id
            and i.display_name == display_name
            and not i.equipped
        ),
        None,
    )
    if same is not None:
        inverse = [{"table": "inventory", "id": same.id, "field": "qty", "before": same.qty}]
        same.qty += qty
        ctx.world.invalidate(ch.id)
        return same.id, inverse
    row = InventoryItem(
        character_id=ch.id,
        item_template_id=template_id,
        display_name=display_name,
        qty=qty,
        world_entity_id=world_entity_id,
    )
    ctx.session.add(row)
    await ctx.session.flush()
    items.append(row)
    ctx.world.invalidate(ch.id)
    return row.id, [{"table": "inventory", "op": "delete", "id": row.id}]


async def _remove_from_inventory(ctx: ToolContext, ch: Character, it: InventoryItem, qty: int) -> list[dict]:
    if it.world_entity_id is not None and qty != 1:
        raise ToolError("уникальный предмет переносится целиком")
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
                "world_entity_id": it.world_entity_id,
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
    if it.world_entity_id is not None:
        entity = _unique_inventory_entity(ctx, it)
        inverse.append({"table": "entities", "id": entity.id, "field": "state", "before": copy.deepcopy(entity.state)})
        entity.state = _object_state(entity, physical="destroyed")
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
    if rec.data.get("unique") and a.qty != 1:
        raise ToolError("уникальный предмет нельзя разместить стопкой")
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
    unique = bool(rec and rec.data.get("unique"))
    if unique and qty != 1:
        raise ToolError("уникальный предмет не может быть стопкой")
    for en in ctx.world.in_scene_entities(place):
        st = en.state or {}
        here = grid.pos_of(ctx.world, en.id).cell == cell if cell is not None else en.zone == zone and "cell" not in st
        same = en.template_id == template_id and st.get("display_name") == display_name and here
        if not unique and is_scene_item(en) and same and not read_world_object(en).unique:
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
            **({"world_object": _world_item_state()} if unique else {}),
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
    if is_nested(en):
        raise ToolError("сначала извлеките предмет из контейнера")
    unique = read_world_object(en).unique
    have = int(st.get("qty") or 1)
    if unique and (have != 1 or a.qty not in (None, 1)):
        raise ToolError("уникальный предмет нельзя делить на части")
    qty = a.qty or have
    if qty > have:
        raise ToolError(f"здесь лежит только {have} шт. «{en.name}»")
    if en.template_id != FOUND_ITEM:
        ctx.world.catalog.get(en.template_id or "", "item_template")  # шаблон пропал из пакета — брать нечего
    inverse = (
        [
            {"table": "entities", "id": en.id, "field": "state", "before": copy.deepcopy(en.state)},
            {"table": "entities", "id": en.id, "field": "location_id", "before": en.location_id},
        ]
        if unique
        else [{"table": "entities", "op": "restore", "row": _entity_row(en)}]
    )
    if unique:
        if en.location_id is None:
            raise ToolError("уникальный предмет уже перенесён")
        # Identity stays in Entity, while InventoryItem links the current owner.
        inv_id, inv = await _add_to_inventory(
            ctx, ch, en.template_id, st.get("display_name"), 1, world_entity_id=en.id
        )
        en.location_id = None
        en.state = _object_state(en, container_id=None)
    else:
        inv_id, inv = await _add_to_inventory(ctx, ch, en.template_id, st.get("display_name"), qty)
    inverse += inv
    result = {"character": ch.name, "item": en.name, "qty": qty, "inventory_id": inv_id, "left": have - qty}
    await ctx.record("pick_up_item", actor_id=ch.id, target_id=en.id, payload=result, inverse=inverse)
    many = f" ×{qty}" if qty > 1 else ""
    ctx.outbox.append({"kind": "system", "content": f"{ch.name} подбирает «{en.name}»{many}: предмет в инвентаре."})
    if not unique and qty == have:
        await ctx.session.delete(en)
        ctx.world.entities.pop(en.id, None)
    elif not unique:
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
    where = grid.pos_of(ctx.world, ch.id).cell  # герой на клетке — вещь ложится у его ног
    if it.world_entity_id is not None:
        en = _unique_inventory_entity(ctx, it)
        inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
        inverse.append({"table": "entities", "id": en.id, "field": "location_id", "before": None})
        en.location_id = ctx.world.place_of(ch)
        en.zone = "melee"
        en.state = _object_state(en, container_id=None)
        if where is not None:
            grid.set_cell(ctx.world, en.id, where)
    else:
        inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
        en, inv = await _put_in_scene(
            ctx, template, display, a.qty, "melee", place=ctx.world.place_of(ch), cell=where
        )
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
    if it.world_entity_id is not None:
        _unique_inventory_entity(ctx, it)
        if a.qty != 1:
            raise ToolError("уникальный предмет передаётся целиком")
        inverse = [{"table": "inventory", "id": it.id, "field": "character_id", "before": ch.id}]
        ctx.world.inventory[ch.id].remove(it)
        ctx.world.inventory.setdefault(to.id, []).append(it)
        it.character_id = to.id
        ctx.world.invalidate(ch.id)
        ctx.world.invalidate(to.id)
        inv_id = it.id
        inv = []
    else:
        inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
        inv_id, inv = await _add_to_inventory(ctx, to, template, display, a.qty)
    result = {"from": ch.name, "to": to.name, "item": name, "qty": a.qty, "inventory_id": inv_id}
    await ctx.record("pass_item", actor_id=ch.id, target_id=to.id, payload=result, inverse=inverse + inv)
    ctx.outbox.append(
        {"kind": "system", "content": f"{ch.name} передаёт {to.name} «{name}»{f' ×{a.qty}' if a.qty > 1 else ''}."}
    )
    return result


# --- persistent containers and nested world objects ---


class CreateContainerArgs(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field("", max_length=500)
    location_id: str | None = Field(None, description=PLACE_HINT)
    zone: Zone = "near"
    visual_key: str = Field("item:chest", pattern=r"^item:[a-z][a-z0-9_-]*$")


@tool(
    "create_container",
    "Создаёт постоянный пустой контейнер. Содержимое не генерируется автоматически.",
    CreateContainerArgs,
    ids={"location_id": "places"},
    closes=False,
)
async def create_container(ctx: ToolContext, a: CreateContainerArgs) -> dict:
    place = ctx.world.place_arg(a.location_id, "стоит контейнер")
    en = Entity(
        campaign_id=ctx.campaign.id,
        kind="object",
        name=a.name,
        description=a.description,
        location_id=place,
        zone=a.zone,
        state={
            "visual_key": a.visual_key,
            "world_object": {
                "schema_version": 1,
                "role": "container",
                "unique": True,
                "container_id": None,
                "capabilities": ["inspect", "open", "close", "put", "take"],
                "access": {"open": False, "locked": False},
                "contents": {"status": "ready"},
                "physical": "intact",
                "revision": 0,
            },
        },
    )
    ctx.session.add(en)
    await ctx.session.flush()
    ctx.world.entities[en.id] = en
    result = {"container_id": en.id, "name": en.name}
    await ctx.record(
        "create_container",
        target_id=en.id,
        payload=result,
        inverse=[{"table": "entities", "op": "delete", "id": en.id}],
    )
    return result


def _accessible_container(ctx: ToolContext, character_id: str, container_id: str) -> tuple[Character, Entity]:
    hero = _character(ctx, character_id)
    _can_handle(ctx, hero)
    container = ctx.world.entities.get(container_id)
    if container is None or container.campaign_id != ctx.campaign.id or container.kind != "object":
        raise ToolError("контейнер не найден в текущей кампании")
    try:
        view = read_world_object(container)
        ancestors = container_chain(container, ctx.world.entities)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    if view.role != "container" or view.metadata.get("physical") == "destroyed":
        raise ToolError("объект недоступен как контейнер")
    if container.location_id != ctx.world.place_of(hero):
        raise ToolError("контейнер находится в другой комнате")
    for other in [container, *ancestors]:
        st = other.state or {}
        if st.get("secret") or st.get("hidden"):
            raise ToolError("контейнер скрыт")
    if any(not (parent.state or {}).get("world_object", {}).get("access", {}).get("open") for parent in ancestors):
        raise ToolError("сначала откройте внешний контейнер")
    return hero, container


class ContainerAccessArgs(BaseModel):
    character_id: str
    container_id: str
    opened: bool = True


@tool(
    "open_container",
    "Открывает или закрывает доступный контейнер; запертый требует отдельного разрешённого действия.",
    ContainerAccessArgs,
    ids={"character_id": "characters"},
)
async def open_container(ctx: ToolContext, a: ContainerAccessArgs) -> dict:
    hero, container = _accessible_container(ctx, a.character_id, a.container_id)
    wo = read_world_object(container).metadata
    access = dict(wo.get("access") or {})
    if a.opened and access.get("locked"):
        raise ToolError("контейнер заперт")
    inverse = [{"table": "entities", "id": container.id, "field": "state", "before": copy.deepcopy(container.state)}]
    container.state = _object_state(container, access={**access, "open": a.opened})
    result = {"container_id": container.id, "opened": a.opened}
    await ctx.record("open_container", actor_id=hero.id, target_id=container.id, payload=result, inverse=inverse)
    return result


class ContainerMoveArgs(BaseModel):
    character_id: str
    container_id: str
    object_id: str


def _validate_container_move(ctx: ToolContext, container: Entity, obj: Entity) -> None:
    if obj.id == container.id or obj.kind != "object" or obj.campaign_id != ctx.campaign.id:
        raise ToolError("нельзя поместить объект в самого себя или чужой мир")
    if obj.location_id != container.location_id:
        raise ToolError("вещь и контейнер должны находиться в одном месте")
    try:
        chain = container_chain(container, ctx.world.entities)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    if any(parent.id == obj.id for parent in chain):
        raise ToolError("контейнер нельзя поместить в собственного потомка")
    if (obj.state or {}).get("hidden") or (obj.state or {}).get("secret"):
        raise ToolError("объект скрыт")


@tool(
    "store_object",
    "Помещает целый предмет сцены или небольшой контейнер в открытый контейнер, без повторной генерации добычи.",
    ContainerMoveArgs,
    ids={"character_id": "characters"},
)
async def store_object(ctx: ToolContext, a: ContainerMoveArgs) -> dict:
    hero, container = _accessible_container(ctx, a.character_id, a.container_id)
    if not read_world_object(container).metadata.get("access", {}).get("open"):
        raise ToolError("контейнер закрыт")
    obj = ctx.world.entities.get(a.object_id)
    if obj is None:
        raise ToolError("объект не найден")
    if is_nested(obj):
        raise ToolError("объект уже находится внутри контейнера")
    _validate_container_move(ctx, container, obj)
    inverse = [{"table": "entities", "id": obj.id, "field": "state", "before": copy.deepcopy(obj.state)}]
    if (obj.state or {}).get("world_object") is None:
        role = "item" if is_scene_item(obj) else "prop"
        base = {"schema_version": 1, "role": role, "unique": False, "capabilities": [], "revision": 0}
        obj.state = {**(obj.state or {}), "world_object": base}
    obj.state = _object_state(obj, container_id=container.id)
    result = {"object_id": obj.id, "container_id": container.id}
    await ctx.record("store_object", actor_id=hero.id, target_id=obj.id, payload=result, inverse=inverse)
    return result


@tool(
    "retrieve_object",
    "Достаёт целый объект из открытого контейнера на пол той же комнаты.",
    ContainerMoveArgs,
    ids={"character_id": "characters"},
)
async def retrieve_object(ctx: ToolContext, a: ContainerMoveArgs) -> dict:
    hero, container = _accessible_container(ctx, a.character_id, a.container_id)
    if not read_world_object(container).metadata.get("access", {}).get("open"):
        raise ToolError("контейнер закрыт")
    obj = ctx.world.entities.get(a.object_id)
    if obj is None or obj.campaign_id != ctx.campaign.id or container_parent(obj) != container.id:
        raise ToolError("этого объекта нет в контейнере")
    inverse = [{"table": "entities", "id": obj.id, "field": "state", "before": copy.deepcopy(obj.state)}]
    obj.state = _object_state(obj, container_id=None)
    result = {"object_id": obj.id, "container_id": container.id}
    await ctx.record("retrieve_object", actor_id=hero.id, target_id=obj.id, payload=result, inverse=inverse)
    return result


class InspectContainerArgs(BaseModel):
    character_id: str
    container_id: str


@tool(
    "inspect_container",
    "Показывает содержимое только открытого доступного контейнера; ничего не генерирует.",
    InspectContainerArgs,
    ids={"character_id": "characters"},
    mutating=False,
)
async def inspect_container(ctx: ToolContext, a: InspectContainerArgs) -> dict:
    _, container = _accessible_container(ctx, a.character_id, a.container_id)
    if not read_world_object(container).metadata.get("access", {}).get("open"):
        raise ToolError("контейнер закрыт")
    contents = [
        {"id": obj.id, "name": obj.name, "qty": (obj.state or {}).get("qty", 1)}
        for obj in ctx.world.entities.values()
        if container_parent(obj) == container.id and obj.campaign_id == ctx.campaign.id
    ]
    return {"container_id": container.id, "contents": contents}
