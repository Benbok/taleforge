"""Предметы: инвентарь героев и вещи в сцене."""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import economy, reach
from app.core import positions as grid
from app.core.character_form import current_form
from app.core.object_policy import concealed, hidden_feature, observe, revealed_to
from app.core.weapon_enchantments import release_weapon
from app.core.world import is_scene_item
from app.core.world_objects import container_chain, container_parent, is_nested, read_world_object
from app.db.models import Character, Entity, InventoryItem, Knowledge, now
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
    _can_handle_form(ctx, ch)
    it = next((i for i in ctx.world.inventory.get(ch.id, []) if i.id == a.inventory_id), None)
    if it is None:
        raise ToolError(f"у {ch.name} нет предмета {a.inventory_id}: рука нащупывает пустоту")
    if it.expires_at is not None and ctx.world.scene.game_time >= it.expires_at:
        raise ToolError(f"«{ctx.world.item_name(it)}» потеряла силу: срок действия истёк")
    if it.item_template_id == FOUND_ITEM:
        raise ToolError(
            f"«{ctx.world.item_name(it)}» — обычная вещь без механики: её применение реши проверкой",
            code="item_use_unsupported",
            category="unsupported",
        )
    rec = ctx.world.catalog.get(it.item_template_id, "item_template")
    if rec.data.get("spell_scroll"):
        from app.tools.spells import read_scroll

        return await read_scroll(ctx, ch, it, rec, [a.target_id] if a.target_id else [])
    ops = rec.data.get("modifiers") or rec.data.get("use") or []
    if not ops:
        raise ToolError(
            f"у предмета {rec.name} нет механики применения",
            code="item_use_unsupported",
            category="unsupported",
        )
    tgt = ctx.world.actor(a.target_id or ch.id)
    _alive(tgt, "Цель")
    if it.item_template_id == "item.goodberry" and tgt.id != ch.id:
        if (
            ctx.world.place_of(ch) != ctx.world.actor_place(tgt.id)
            or ctx.world.distance_ft(ctx.world.actor(ch.id), tgt) > 5
            or grid.wall_between(ctx.world, ch.id, tgt.id)
        ):
            raise ToolError("чтобы дать ягоду, сначала подойдите к получателю вплотную")
    inv = [
        snapshot(tgt),
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
                "expires_at": it.expires_at,
            },
        },
    ]
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
        "remaining_qty": max(0, it.qty),
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
    if a.item_template_id == "item.goodberry":
        raise ToolError(
            "ягоды создаёт cast_spell и уже кладёт в инвентарь; повторная выдача через give_item недопустима"
        )
    ch = _character(ctx, a.character_id)
    _can_handle_form(ctx, ch)
    rec = ctx.world.catalog.get(a.item_template_id, "item_template")
    if rec.pack_id.startswith("campaign.") and a.qty > 10:
        raise ToolError("придуманный мастером предмет выдаётся не больше 10 штук за раз")
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
    "Герой сохраняет новую находку, которой ещё нет среди объектов кампании и инвентарей: нашёл камень, "
    "выломал арматуру из стены. Существующие вещи, включая вещи NPC, перемещайте через pick_up_item по entity_id. "
    "Для stolen/pried нужен успешный roll_check этого героя в текущем ходу; from_id не создаёт владение вещью.",
    KeepFoundArgs,
    ids={"character_id": "characters", "from_id": "subjects"},
)
async def keep_found_item(ctx: ToolContext, a: KeepFoundArgs) -> dict:
    ch = _character(ctx, a.character_id)
    _can_handle(ctx, ch)
    if a.how in ("stolen", "pried"):
        _successful_item_check(ctx, ch.id, a.from_id)
    name_key = _item_name_key(a.name)
    if any(
        en.campaign_id == ctx.campaign.id and en.kind == "object" and _item_name_key(en.name) == name_key
        for en in ctx.world.entities.values()
    ) or any(
        _item_name_key(ctx.world.item_name(it)) == name_key for items in ctx.world.inventory.values() for it in items
    ):
        raise ToolError("такая вещь уже существует: перемещайте её через pick_up_item, pass_item или drop_item")
    src = ctx.world.entities.get(a.from_id or "") or ctx.world.characters.get(a.from_id or "")
    if a.from_id:
        if src is None or src.campaign_id != ctx.campaign.id:
            raise ToolError("источник вещи не найден в текущей кампании")
        place = ctx.world.place_of(src) if isinstance(src, Character) else src.location_id
        if place != ctx.world.place_of(ch):
            raise ToolError("источник вещи находится в другом месте")
        # Actors cannot supply invented possessions. Existing possessions are moved by id.
        if isinstance(src, Character) or src.kind == "creature":
            raise ToolError("у источника нет такой подтверждённой вещи: существующий предмет берите через pick_up_item")
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
    rec = ctx.world.catalog.find(template, "item_template") if a.kind == "template" else None
    unique = bool(rec and rec.data.get("unique"))
    if unique and a.qty != 1:
        raise ToolError("уникальный экземпляр нельзя сохранить стопкой")
    entity = await _new_unique_item(ctx, template, a.name) if unique else None
    inv_id, inverse = await _add_to_inventory(
        ctx, ch, template, a.name, a.qty, world_entity_id=entity.id if entity else None
    )
    if entity is not None:
        inverse.append({"table": "entities", "op": "delete", "id": entity.id})
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


def _item_name_key(name: str) -> str:
    return " ".join(name.casefold().split())


def _successful_item_check(ctx: ToolContext, character_id: str, source_id: str | None) -> None:
    checks = [
        ev
        for ev in ctx.events
        if ev.tool == "roll_check"
        and ev.actor_id == character_id
        and ev.turn_id == ctx.turn_id
        and ev.campaign_id == ctx.campaign.id
    ]
    check = checks[-1] if checks else None
    if (
        check is None
        or check.payload.get("kind") != "check"
        or check.payload.get("success") is not True
        or (check.target_id is not None and check.target_id != source_id)
    ):
        raise ToolError("сначала нужен успешный roll_check этого героя в текущем ходу для этой добычи")


def _world_item_state(*, unique: bool = True) -> dict:
    return {
        "schema_version": 1,
        "role": "item",
        "capabilities": ["inspect", "take", "put"],
        "unique": unique,
        "container_id": None,
        "revision": 0,
        "physical": "intact",
    }


def _object_state(entity: Entity, **changes: object) -> dict:
    previous = dict((entity.state or {}).get("world_object") or _world_item_state())
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
    if read_world_object(entity).metadata.get("physical") == "destroyed":
        raise ToolError("уникальный предмет уничтожен")
    return entity


async def _add_to_inventory(
    ctx: ToolContext,
    ch: Character,
    template_id: str,
    display_name: str | None,
    qty: int,
    *,
    world_entity_id: str | None = None,
    expires_at: int | None = None,
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
            and i.expires_at == expires_at
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
        expires_at=expires_at,
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
                "expires_at": it.expires_at,
            },
        }
    ]
    released = release_weapon(ch, it.id)
    if released:
        inverse.append(released)
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
    _can_handle_form(ctx, ch)


def _can_handle_form(ctx: ToolContext, ch: Character) -> None:
    form = current_form(ch, ctx.world.scene.game_time)
    if form and not form.get("can_handle_items", False):
        raise ToolError(
            f"{ch.name}: облик «{form['name']}» не позволяет брать и передавать снаряжение. "
            "Предмет остаётся на месте; сначала нужно вернуться в подходящий облик.",
            code="form_cannot_handle_items",
            category="rule_denial",
        )


class TakeItemArgs(BaseModel):
    character_id: str
    inventory_id: str
    qty: int = Field(1, ge=1, le=100)
    reason: str


@tool(
    "take_item",
    "Списывает обычный предмет из инвентаря персонажа. Уникальные вещи переносите через pass_item или drop_item; "
    "вещь у NPC забирают через pick_up_item.",
    TakeItemArgs,
    ids={"character_id": "characters", "inventory_id": "inventory"},
)
async def take_item(ctx: ToolContext, a: TakeItemArgs) -> dict:
    ch = _character(ctx, a.character_id)
    it = _own_item(ctx, ch, a.inventory_id)
    if it.world_entity_id is not None:
        raise ToolError("уникальный предмет нельзя списать: используйте pass_item или drop_item")
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
    _can_handle_form(ctx, ch)
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
    if not a.equipped:
        released = release_weapon(ch, it.id)
        if released:
            inverse.append(released)
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
    discovery_check_event_id: str | None = Field(
        None,
        description="id успешного roll_check(perception/investigation) текущего хода, результат которого — находка",
    )


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
    if a.discovery_check_event_id is not None:
        check = next((ev for ev in ctx.events if ev.id == a.discovery_check_event_id), None)
        hero = ctx.world.characters.get(check.actor_id or "") if check is not None else None
        if (
            check is None
            or check.tool != "roll_check"
            or check.turn_id != ctx.turn_id
            or check.campaign_id != ctx.campaign.id
            or check.payload.get("success") is not True
            or check.payload.get("kind") != "check"
            or check.payload.get("stat") not in ("perception", "investigation")
            or hero is None
            or ctx.world.place_of(hero) != (place or ctx.world.home())
        ):
            raise ToolError("находка требует успешного roll_check поиска этого хода героем в том же месте")
    cell = _floor(ctx, place or ctx.world.home(), a.cell)
    if rec.data.get("unique") and a.qty != 1:
        raise ToolError("уникальный предмет нельзя разместить стопкой")
    en, inverse = await _put_in_scene(ctx, rec.id, a.display_name, a.qty, a.zone, a.description, place, cell)
    result = {"entity_id": en.id, "item": en.name, "qty": a.qty}
    if a.cell is not None:
        result["cell"] = list(a.cell)
    await ctx.record(
        "place_item",
        target_id=en.id,
        payload={
            **result,
            "reason": a.reason,
            "template": rec.id,
            **({"discovery_check_event_id": a.discovery_check_event_id} if a.discovery_check_event_id else {}),
        },
        inverse=inverse,
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
    *,
    container_id: str | None = None,
    force_new: bool = False,
    expires_at: int | None = None,
    force_unique: bool = False,
    generation_ref: str | None = None,
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
    unique = bool(rec and rec.data.get("unique")) or force_unique
    if unique and qty != 1:
        raise ToolError("уникальный предмет не может быть стопкой")
    for en in [] if force_new or container_id is not None else ctx.world.in_scene_entities(place):
        st = en.state or {}
        here = grid.pos_of(ctx.world, en.id).cell == cell if cell is not None else en.zone == zone and "cell" not in st
        same = (
            en.template_id == template_id
            and st.get("display_name") == display_name
            and st.get("expires_at") == expires_at
            and here
        )
        if (
            not unique
            and is_scene_item(en)
            and same
            and not read_world_object(en).unique
            and not read_world_object(en).metadata.get("generation_ref")
        ):
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
            **({"expires_at": expires_at} if expires_at is not None else {}),
            **({"visual_key": visual_key} if visual_key is not None else {}),
            **(
                {
                    "world_object": {
                        **_world_item_state(unique=unique),
                        "container_id": container_id,
                        **({"origin": "generated", "generation_ref": generation_ref} if generation_ref else {}),
                    }
                }
                if unique or container_id is not None or generation_ref
                else {}
            ),
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
    how: Literal["found", "given", "stolen", "looted"] = Field(
        "found", description="у владельца-NPC: given — отдал, stolen — после успешного roll_check, looted — у павшего"
    )


@tool(
    "pick_up_item",
    "Герой подбирает предмет, лежащий в сцене: предмет переходит в его инвентарь и остаётся там. Бросок не нужен, "
    "если предмет никто не охраняет. Вещь NPC берите по её entity_id с how=given/stolen/looted; "
    "кража требует успешной проверки, добыча — павшего владельца.",
    PickUpArgs,
    ids={"character_id": "characters", "entity_id": "scene_items"},
)
async def pick_up_item(ctx: ToolContext, a: PickUpArgs) -> dict:
    ch = _character(ctx, a.character_id)
    _can_handle(ctx, ch)
    en = ctx.world.entities.get(a.entity_id)
    parent = ctx.world.entities.get(container_parent(en) or "") if en is not None else None
    owner = parent if parent is not None and parent.kind == "creature" else None
    if (
        en is None
        or en.campaign_id != ctx.campaign.id
        or (owner is None and en not in ctx.world.in_scene_entities(ctx.world.place_of(ch)))
    ):
        raise ToolError(f"предмета {a.entity_id} нет рядом с {ch.name}")
    if not is_scene_item(en):
        raise ToolError(f"{en.name} — не предмет: его нельзя положить в инвентарь")
    st = dict(en.state or {})
    if is_nested(en) and owner is None:
        raise ToolError("сначала извлеките предмет из контейнера")
    found = await revealed_to(ctx.session, ch.id)
    if owner is not None:
        _npc_item_access(ctx, ch, owner, found)
        if en.id not in found:
            raise ToolError("вещь владельца ещё не обнаружена")
        if a.how == "stolen":
            _successful_item_check(ctx, ch.id, owner.id)
        elif a.how == "looted":
            if ctx.world.actor(owner.id).hp.current > 0:
                raise ToolError("владелец ещё не побеждён: вещь можно получить или украсть")
        elif a.how != "given":
            raise ToolError("вещь принадлежит NPC: укажите how=given, stolen или looted")
    elif concealed(en, ctx.world.entities, found):
        raise ToolError(f"предмета {a.entity_id} не видно: сначала его находят")
    if read_world_object(en).metadata.get("physical") == "destroyed":
        raise ToolError("предмет уничтожен")
    room_id = en.location_id
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
        # Lock the persistent identity before granting ownership. A stale scene snapshot
        # cannot give the same artifact to two heroes in concurrent master turns.
        query = (
            select(Entity)
            .where(Entity.id == en.id, Entity.campaign_id == ctx.campaign.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        en = (await ctx.session.scalars(query)).one_or_none()
        if en is None or (
            container_parent(en) != owner.id
            if owner is not None
            else en.location_id != ctx.world.place_of(ch) or is_nested(en)
        ):
            raise ToolError("уникальный предмет уже перемещён")
        owned = await ctx.session.scalar(select(InventoryItem.id).where(InventoryItem.world_entity_id == en.id))
        if owned is not None:
            raise ToolError("уникальный предмет уже принадлежит персонажу")
        # Identity stays in Entity, while InventoryItem links the current owner.
        if owner is None:
            inverse += _approach(ctx, ch, en, walk=True)
        inv_id, inv = await _add_to_inventory(ctx, ch, en.template_id, st.get("display_name"), 1, world_entity_id=en.id)
        en.location_id = None
        carried = _object_state(en, container_id=None)
        carried.pop("cell", None)
        en.state = carried
    else:
        if owner is None:
            inverse += _approach(ctx, ch, en, walk=True)
        inv_id, inv = await _add_to_inventory(
            ctx, ch, en.template_id, st.get("display_name"), qty, expires_at=st.get("expires_at")
        )
    inverse += inv
    if unique or qty == have:
        inverse += detach_feature(ctx, en.id, room_id)
    result = {"character": ch.name, "item": en.name, "qty": qty, "inventory_id": inv_id, "left": have - qty}
    if owner is not None:
        result.update({"from_id": owner.id, "from": owner.name, "how": a.how})
    if not unique and qty == have:
        await ctx.session.delete(en)
        ctx.world.entities.pop(en.id, None)
    elif not unique:
        en.state = {**st, "qty": have - qty}
    await ctx.record("pick_up_item", actor_id=ch.id, target_id=en.id, payload=result, inverse=inverse)
    many = f" ×{qty}" if qty > 1 else ""
    ctx.outbox.append({"kind": "system", "content": f"{ch.name} подбирает «{en.name}»{many}: предмет в инвентаре."})
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
        inverse.extend(
            [
                {"table": "entities", "id": en.id, "field": "location_id", "before": en.location_id},
                {"table": "entities", "id": en.id, "field": "zone", "before": en.zone},
                {"table": "entities", "id": en.id, "field": "state", "before": copy.deepcopy(en.state)},
            ]
        )
        en.location_id = ctx.world.place_of(ch)
        en.zone = "melee"
        en.state = _object_state(en, container_id=None)
        if where is not None:
            grid.set_cell(ctx.world, en.id, where)
    else:
        inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
        en, inv = await _put_in_scene(
            ctx, template, display, a.qty, "melee", place=ctx.world.place_of(ch), cell=where, expires_at=it.expires_at
        )
        inverse += inv
    await observe(ctx, en.location_id, inverse, only=[en.id])
    result = {"character": ch.name, "item": name, "qty": a.qty, "entity_id": en.id}
    from app.core.layout.furnish import sync_objects

    sync_objects(ctx, inverse, include={en.id})
    await ctx.record("drop_item", actor_id=ch.id, target_id=en.id, payload=result, inverse=inverse)
    return result


class PassItemArgs(BaseModel):
    character_id: str = Field(description="кто отдаёт")
    to_character_id: str | None = Field(None, description="кому из героев отряда; укажите ровно одного получателя")
    to_entity_id: str | None = Field(None, description="NPC или существу сцены; укажите ровно одного получателя")
    inventory_id: str
    qty: int = Field(1, ge=1, le=100)


@tool(
    "pass_item",
    "Герой передаёт предмет из своего инвентаря герою (to_character_id) или NPC (to_entity_id). "
    "Уникальная вещь сохраняет entity_id; вернуть вещь NPC можно через pick_up_item.",
    PassItemArgs,
    ids={
        "character_id": "characters",
        "to_character_id": "characters",
        "to_entity_id": "entities",
        "inventory_id": "inventory",
    },
)
async def pass_item(ctx: ToolContext, a: PassItemArgs) -> dict:
    ch = _character(ctx, a.character_id)
    if (a.to_character_id is None) == (a.to_entity_id is None):
        raise ToolError("укажите ровно одного получателя: to_character_id или to_entity_id")
    if a.to_entity_id is not None:
        return await _pass_to_npc(ctx, ch, a)
    to = _character(ctx, a.to_character_id)
    if ch.id == to.id:
        raise ToolError("отдать предмет самому себе нельзя")
    _can_handle(ctx, ch)
    _can_handle_form(ctx, to)
    it = _own_item(ctx, ch, a.inventory_id)
    template, display = it.item_template_id, it.display_name
    name = ctx.world.item_name(it)
    if it.world_entity_id is not None:
        _unique_inventory_entity(ctx, it)
        if a.qty != 1:
            raise ToolError("уникальный предмет передаётся целиком")
        inverse = [{"table": "inventory", "id": it.id, "field": "character_id", "before": ch.id}]
        ctx.world.inventory[ch.id].remove(it)
        released = release_weapon(ch, it.id)
        if released:
            inverse.append(released)
        ctx.world.inventory.setdefault(to.id, []).append(it)
        it.character_id = to.id
        ctx.world.invalidate(ch.id)
        ctx.world.invalidate(to.id)
        inv_id = it.id
        inv = []
    else:
        inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
        inv_id, inv = await _add_to_inventory(ctx, to, template, display, a.qty, expires_at=it.expires_at)
    result = {"from": ch.name, "to": to.name, "item": name, "qty": a.qty, "inventory_id": inv_id}
    await ctx.record("pass_item", actor_id=ch.id, target_id=to.id, payload=result, inverse=inverse + inv)
    ctx.outbox.append(
        {"kind": "system", "content": f"{ch.name} передаёт {to.name} «{name}»{f' ×{a.qty}' if a.qty > 1 else ''}."}
    )
    return result


def _npc_item_access(ctx: ToolContext, ch: Character, npc: Entity, found: frozenset[str]) -> None:
    if npc.campaign_id != ctx.campaign.id or npc.kind != "creature":
        raise ToolError("получатель должен быть NPC или существом текущей кампании")
    if npc.location_id != ctx.world.place_of(ch) or is_nested(npc):
        raise ToolError("NPC находится в другом месте или недоступен")
    if concealed(npc, ctx.world.entities, found):
        raise ToolError("NPC скрыт: сначала его находят")
    if grid.distance(grid.pos_of(ctx.world, ch.id), grid.pos_of(ctx.world, npc.id)) > 5:
        raise ToolError("до NPC не дотянуться: сначала подойдите вплотную")
    if grid.wall_between(ctx.world, ch.id, npc.id) or grid.pos_of(ctx.world, npc.id).cover == "total":
        raise ToolError("до NPC не дотянуться: путь закрыт")
    problem, _ = reach.approach_route(ctx.world, ch.id, npc, fighting=True)
    if problem:
        raise ToolError(problem)


async def _pass_to_npc(ctx: ToolContext, ch: Character, a: PassItemArgs) -> dict:
    _can_handle(ctx, ch)
    npc = ctx.world.entities.get(a.to_entity_id or "")
    if npc is None:
        raise ToolError("NPC не найден")
    _npc_item_access(ctx, ch, npc, await revealed_to(ctx.session, ch.id))
    _alive(ctx.world.actor(npc.id), "Получатель")
    it = _own_item(ctx, ch, a.inventory_id)
    name = ctx.world.item_name(it)
    if it.world_entity_id is not None:
        en = _unique_inventory_entity(ctx, it)
        inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
        inverse.extend(
            [
                {"table": "entities", "id": en.id, "field": "location_id", "before": en.location_id},
                {"table": "entities", "id": en.id, "field": "zone", "before": en.zone},
                {"table": "entities", "id": en.id, "field": "state", "before": copy.deepcopy(en.state)},
            ]
        )
        en.location_id = npc.location_id
        en.zone = npc.zone
        en.state = _object_state(en, container_id=npc.id)
    else:
        inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
        en, inv = await _put_in_scene(
            ctx,
            it.item_template_id,
            it.display_name,
            a.qty,
            npc.zone,
            place=npc.location_id,
            container_id=npc.id,
            expires_at=it.expires_at,
        )
        inverse += inv
    # Giving an object proves this hero knows it, without revealing other NPC possessions.
    row = await ctx.session.get(Knowledge, (ch.id, en.id))
    if row is None:
        row = Knowledge(character_id=ch.id, entity_id=en.id, level=0, revealed_at=now())
        ctx.session.add(row)
        inverse.append({"table": "knowledge", "op": "delete", "id": [ch.id, en.id]})
    elif row.revealed_at is None:
        inverse.append({"table": "knowledge", "id": [ch.id, en.id], "field": "revealed_at", "before": None})
        row.revealed_at = now()
    ctx.world.revealed.setdefault(ch.id, set()).add(en.id)
    ctx.changed.add(en.id)
    result = {"from": ch.name, "to": npc.name, "item": name, "qty": a.qty, "entity_id": en.id}
    await ctx.record("pass_item", actor_id=ch.id, target_id=npc.id, payload=result, inverse=inverse)
    ctx.outbox.append(
        {"kind": "system", "content": f"{ch.name} передаёт {npc.name} «{name}»{f' ×{a.qty}' if a.qty > 1 else ''}."}
    )
    return result


# --- persistent containers and nested world objects ---


def _container_state(*, status: str = "ready", profile: str | None = None) -> dict:
    """Один формат состояния для ручных и сгенерированных контейнеров."""
    return {
        "schema_version": 1,
        "role": "container",
        "unique": True,
        "container_id": None,
        "capabilities": ["inspect", "open", "close", "put", "take"],
        "access": {"open": False, "locked": False},
        "contents": {"status": status},
        "physical": "intact",
        "revision": 0,
        **({"generation_profile": profile, "origin": "generated"} if profile else {}),
    }


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
            "world_object": _container_state(),
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


def detach_feature(ctx: ToolContext, entity_id: str, room_id: str | None) -> list[dict]:
    """Объект ушёл с пола комнаты целиком (поднят, убран в контейнер): его деталь эскиза уходит вместе с ним в той
    же транзакции, иначе вернувшаяся вещь всплыла бы на старом месте мебели (docs/world-objects-delivery1.md, §2.3)."""
    room = ctx.world.entities.get(room_id or "")
    sk = (room.state or {}).get("sketch") if room is not None else None
    if not isinstance(sk, dict) or not any(f.get("entity_id") == entity_id for f in sk.get("features") or []):
        return []
    before = copy.deepcopy(room.state)
    features = [f for f in sk.get("features") or [] if f.get("entity_id") != entity_id]
    sketch_now = {**sk, "features": features, "edit_rev": int(sk.get("edit_rev") or 0) + 1, "auto": False}
    placement_rev = int((room.state or {}).get("placement_rev") or 0) + 1
    room.state = {**(room.state or {}), "sketch": sketch_now, "placement_rev": placement_rev}
    return [{"table": "entities", "id": room.id, "field": "state", "before": before}]


def _approach(ctx: ToolContext, hero: Character, container: Entity, *, walk: bool) -> list[dict]:
    """Дотянуться до привязанного к эскизу контейнера: с клетки подхода, с доступной стороны. Вне боя герой
    подходит сам (``walk``) — клетка меняется, обратная запись в том же событии."""
    from app.core import combat

    w = ctx.world
    fighting = combat.in_combat(ctx) and combat.fights(w.scene, w.characters, w.entities, hero.id)
    problem, route = reach.approach_route(w, hero.id, container, fighting=fighting)
    if problem:
        raise ToolError(problem)
    if not route or not walk:
        return []
    inverse = [{"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(w.scene.state)}]
    grid.set_cell(w, hero.id, route[-1])
    ctx.changed.add(hero.id)
    return inverse


async def _accessible_container(
    ctx: ToolContext, character_id: str, container_id: str
) -> tuple[Character, Entity, frozenset[str]]:
    """Общая policy (спецификация §8.2): принадлежность, присутствие, обнаружение тайного этим героем, открытые
    предки. Подход проверяет ``_approach``. Возвращает и то, что герой обнаружил, — для фильтра содержимого."""
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
    found = await revealed_to(ctx.session, hero.id)
    for other in [container, *ancestors]:
        st = other.state or {}
        room = ctx.world.entities.get(other.location_id or "")
        if (st.get("secret") or st.get("hidden") or hidden_feature(room, other.id)) and other.id not in found:
            raise ToolError("контейнер скрыт")
    if any(not (parent.state or {}).get("world_object", {}).get("access", {}).get("open") for parent in ancestors):
        raise ToolError("сначала откройте внешний контейнер")
    return hero, container, found


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
    hero, container, found = await _accessible_container(ctx, a.character_id, a.container_id)
    wo = read_world_object(container).metadata
    access = dict(wo.get("access") or {})
    if a.opened and access.get("locked"):
        raise ToolError("контейнер заперт")
    inverse = _approach(ctx, hero, container, walk=True)
    inverse.append(
        {"table": "entities", "id": container.id, "field": "state", "before": copy.deepcopy(container.state)}
    )
    container.state = _object_state(container, access={**access, "open": a.opened})
    if a.opened:  # открытое содержимое видно присутствующим — снимок наблюдения
        inside = [o.id for o in ctx.world.entities.values() if container_parent(o) == container.id]
        await observe(ctx, container.location_id, inverse, only=inside)
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
    hero, container, found = await _accessible_container(ctx, a.character_id, a.container_id)
    if not read_world_object(container).metadata.get("access", {}).get("open"):
        raise ToolError("контейнер закрыт")
    if await _unexplored(ctx, container) is not None:
        raise ToolError("содержимое контейнера ещё не исследовано: сначала обыщите его")
    obj = ctx.world.entities.get(a.object_id)
    if obj is None:
        raise ToolError("объект не найден")
    if is_nested(obj):
        raise ToolError("объект уже находится внутри контейнера")
    _validate_container_move(ctx, container, obj)
    inverse = _approach(ctx, hero, container, walk=True)
    inverse.append({"table": "entities", "id": obj.id, "field": "state", "before": copy.deepcopy(obj.state)})
    inverse += detach_feature(ctx, obj.id, obj.location_id)
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
    hero, container, found = await _accessible_container(ctx, a.character_id, a.container_id)
    if not read_world_object(container).metadata.get("access", {}).get("open"):
        raise ToolError("контейнер закрыт")
    obj = ctx.world.entities.get(a.object_id)
    if obj is None or obj.campaign_id != ctx.campaign.id or container_parent(obj) != container.id:
        raise ToolError("этого объекта нет в контейнере")
    if concealed(obj, ctx.world.entities, found):
        raise ToolError("этого объекта нет в контейнере")  # тайное внутри не выдаёт себя
    inverse = _approach(ctx, hero, container, walk=True)
    inverse.append({"table": "entities", "id": obj.id, "field": "state", "before": copy.deepcopy(obj.state)})
    obj.state = _object_state(obj, container_id=None)
    from app.core.layout.furnish import sync_objects

    sync_objects(ctx, inverse, include={obj.id})
    await observe(ctx, obj.location_id, inverse, only=[obj.id])
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
    hero, container, found = await _accessible_container(ctx, a.character_id, a.container_id)
    if not read_world_object(container).metadata.get("access", {}).get("open"):
        raise ToolError("контейнер закрыт")
    _approach(ctx, hero, container, walk=False)  # только чтение: проверить, что дотянуться можно, никого не двигая
    unexplored = await _unexplored(ctx, container)
    if unexplored is not None:  # неисследованное содержимое не «пусто»: его ещё нет
        return {"container_id": container.id, "status": unexplored, "contents": None, "note": "не исследован"}
    return {"container_id": container.id, "contents": container_contents(ctx, container, found)}


def container_contents(ctx: ToolContext, container: Entity, found: frozenset[str]) -> list[dict]:
    return [
        {"id": obj.id, "name": obj.name, "qty": (obj.state or {}).get("qty", 1)}
        for obj in ctx.world.entities.values()
        if container_parent(obj) == container.id
        and obj.campaign_id == ctx.campaign.id
        and not concealed(obj, ctx.world.entities, found)  # проверка для этого героя, не для всей кампании
    ]


async def _unexplored(ctx: ToolContext, container: Entity) -> str | None:
    """Публичный статус подготовки содержимого, если оно ещё не готово; None — читать текущие предметы."""
    from app.core.preparation import public_status
    from app.core.world_generation import storage

    row = await storage.find(ctx.session, ctx.campaign.id, container.id, "container_contents")
    if row is None or row.status == "ready":
        return None
    return public_status(row)


async def create_stash_container(
    ctx: ToolContext,
    stash_place_id: str,
    name: str = "Изъятые вещи",
    description: str = "Снаряжение героев, изъятое при пленении.",
) -> Entity:
    """Создаёт постоянный контейнер в тайнике каркаса без требования присутствия отряда в сцене."""
    en = Entity(
        campaign_id=ctx.campaign.id,
        kind="object",
        name=name,
        description=description,
        location_id=stash_place_id,
        zone="near",
        state={
            "visual_key": "item:chest",
            "world_object": _container_state(),
        },
    )
    ctx.session.add(en)
    await ctx.session.flush()
    ctx.world.entities[en.id] = en
    result = {"container_id": en.id, "name": en.name, "location_id": stash_place_id}
    await ctx.record(
        "create_container",
        target_id=en.id,
        payload=result,
        inverse=[{"table": "entities", "op": "delete", "id": en.id}],
    )
    return en


KEPT_CATEGORIES = frozenset({"clothing", "focus", "spellcasting_focus"})
KEPT_TAGS = frozenset(
    {
        "clothing",
        "focus",
        "spellcasting_focus",
        "druidic_focus",
        "holy_symbol",
        "arcane_focus",
        "component_pouch",
    }
)


def is_kept_gear(catalog, item: InventoryItem) -> bool:
    """Остаётся ли предмет при изъятии снаряжения по завязке: одежда и фокусировка заклинателя."""
    rec = catalog.find(item.item_template_id, "item_template")
    if rec is None:
        return False
    data = rec.data or {}
    category = data.get("category")
    if category in KEPT_CATEGORIES:
        return True
    tags = set(data.get("tags") or [])
    return bool(tags & KEPT_TAGS)


async def confiscate_hero_gear(
    ctx: ToolContext,
    hero: Character,
    container: Entity,
    stash_place_id: str,
) -> list[dict]:
    """Изымает снаряжение героя в контейнер тайника, сохраняя только одежду и фокусировку заклинателя.

    Уникальные предметы сохраняют сущность Entity, обычные переносятся в контейнер.
    """
    inv_items = list(ctx.world.inventory.get(hero.id, []))
    total_inverse: list[dict] = []
    has_clothes = False

    for item in inv_items:
        if is_kept_gear(ctx.world.catalog, item):
            rec = ctx.world.catalog.find(item.item_template_id, "item_template")
            if rec and (rec.data.get("category") == "clothing" or "clothing" in (rec.data.get("tags") or [])):
                has_clothes = True
            continue

        item_name = ctx.world.item_name(item)
        qty = item.qty
        unique_en = ctx.world.entities.get(item.world_entity_id) if item.world_entity_id else None

        inverse = await _remove_from_inventory(ctx, hero, item, qty)

        if unique_en is not None:
            inverse.append(
                {"table": "entities", "id": unique_en.id, "field": "location_id", "before": unique_en.location_id}
            )
            inverse.append(
                {"table": "entities", "id": unique_en.id, "field": "state", "before": copy.deepcopy(unique_en.state)}
            )
            unique_en.location_id = stash_place_id
            unique_en.state = _object_state(unique_en, container_id=container.id)
            total_inverse.extend(inverse)
        else:
            _, put_inv = await _put_in_scene(
                ctx,
                item.item_template_id,
                item.display_name,
                qty,
                zone="near",
                place=stash_place_id,
                container_id=container.id,
            )
            inverse.extend(put_inv)
            total_inverse.extend(inverse)

        await ctx.record(
            "confiscate_item",
            actor_id=hero.id,
            target_id=container.id,
            payload={
                "character": hero.name,
                "item": item_name,
                "qty": qty,
                "container_id": container.id,
            },
            inverse=inverse,
        )

    if not has_clothes and ctx.world.catalog.find("item.clothes_common", "item_template"):
        _, add_inv = await _add_to_inventory(ctx, hero, "item.clothes_common", None, 1)
        total_inverse.extend(add_inv)

    ctx.world.invalidate(hero.id)
    return total_inverse
