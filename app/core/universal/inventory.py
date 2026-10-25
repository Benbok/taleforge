"""Entity-backed universal equipment. No class/catalog coupling, no time advancement."""

import hashlib
from typing import Literal

from pydantic import Field
from sqlalchemy import select

from app.core.campaigns import AccessDenied, Conflict
from app.core.universal.clock import lock_campaign
from app.core.universal.profiles import actor_row, load_actor, save_actor
from app.db.models import Character, Entity, Event
from app.rules.universal.contracts import ActorDerived, ClosedModel, Count
from app.rules.universal.exploration import EffectChange, ExplorationOutcome
from app.rules.universal.items import STATUS_NAMES, ItemProfile
from app.rules.universal.mechanics import derive, starting_defense_bonuses


class ItemState(ClosedModel):
    schema_version: Literal[1] = 1
    owner_id: str
    profile: ItemProfile
    quantity: Count = Field(default=1, le=1000)
    equipped: bool = False
    source_key: str


def state_of(row):
    return ItemState.model_validate(row.state["universal_item"])


def store(row, state):
    row.state = {**row.state, "universal_item": state.model_dump(mode="json")}


def resources_of(actor):
    return actor.resources if isinstance(actor, Character) else actor.state.get("resources", {})


def set_resources(actor, resources):
    if isinstance(actor, Character):
        actor.resources = resources
    else:
        actor.state = {**actor.state, "resources": resources}


async def create_item(session, campaign_id, actor_id, profile, source_key, *, quantity=1, equipped=False):
    profile = ItemProfile.model_validate(profile.model_dump())
    if not source_key or len(source_key) > 128:
        raise ValueError("Нужен источник предмета")
    actor = await actor_row(session, campaign_id, actor_id)
    key = "en_" + hashlib.sha256(f"{campaign_id}:{actor_id}:{source_key}".encode()).hexdigest()[:24]
    row = await session.get(Entity, key)
    state = ItemState(owner_id=actor_id, profile=profile, quantity=quantity, equipped=equipped, source_key=source_key)
    if row is not None:
        if state_of(row).profile != profile:
            raise Conflict("Сохранённый профиль предмета неизменяем")
        return row
    row = Entity(
        id=key,
        campaign_id=campaign_id,
        kind="object",
        name=profile.name,
        description=profile.description,
        location_id=actor.location_id,
        state={},
    )
    store(row, state)
    session.add(row)
    await session.flush()
    return row


async def ensure_inventory(session, campaign_id, actor_id):
    await lock_campaign(session, campaign_id)
    actor = await actor_row(session, campaign_id, actor_id, refresh=True)
    if resources_of(actor).get("inventory_initialized"):
        return
    sheet, _ = await load_actor(session, campaign_id, actor_id)
    if sheet.starting_equipment:
        for item in (sheet.starting_equipment.weapon, sheet.starting_equipment.armor):
            profile = ItemProfile(
                name=item.name,
                description=item.description,
                kind=item.kind,
                attribute=item.attack_ability if item.kind == "weapon" else "str",
                base_dice=item.damage_dice if item.kind == "weapon" else "1d6",
                defense_bonus=item.defense_bonus if item.kind == "armor" else 0,
            )
            await create_item(session, campaign_id, actor_id, profile, f"starter:{item.kind}", equipped=True)
    set_resources(actor, {**resources_of(actor), "inventory_initialized": True})
    await session.flush()


async def owned_items(session, campaign_id, actor_id):
    await actor_row(session, campaign_id, actor_id)
    return [
        row
        for row in await session.scalars(
            select(Entity).where(Entity.campaign_id == campaign_id, Entity.kind == "object")
        )
        if "universal_item" in row.state and state_of(row).owner_id == actor_id and state_of(row).quantity > 0
    ]


async def equipped_items(session, campaign_id, actor_id):
    return [row for row in await owned_items(session, campaign_id, actor_id) if state_of(row).equipped]


async def actor_derived(session, campaign_id, actor_id):
    actor = await actor_row(session, campaign_id, actor_id)
    sheet, _ = await load_actor(session, campaign_id, actor_id)
    bonuses = starting_defense_bonuses(sheet)
    if resources_of(actor).get("inventory_initialized"):
        bonuses = [
            state_of(row).profile.defense_bonus
            for row in await equipped_items(session, campaign_id, actor_id)
            if state_of(row).profile.kind == "armor"
        ]
    return derive(sheet, bonuses)


def item_view(row):
    state = state_of(row)
    return dict(
        id=row.id,
        **state.profile.model_dump(mode="json"),
        status_name=STATUS_NAMES[state.profile.status],
        quantity=str(state.quantity),
        equipped=state.equipped,
        slot=state.profile.kind if state.profile.kind != "consumable" else None,
    )


async def _owned(session, campaign_id, actor_id, item_id):
    actor = await actor_row(session, campaign_id, actor_id)
    row = await session.get(Entity, item_id, populate_existing=True)
    if row is None or row.campaign_id != campaign_id or "universal_item" not in row.state:
        raise AccessDenied("Предмет недоступен")
    state = state_of(row)
    if state.owner_id != actor_id or state.quantity < 1 or row.state.get("hidden"):
        raise AccessDenied("Это не ваш доступный предмет")
    return actor, row, state


async def _previous(session, campaign_id, key, binding):
    if not key or len(key) > 64:
        raise ValueError("Неверный ключ операции")
    previous = await session.scalar(select(Event).where(Event.campaign_id == campaign_id, Event.idempotency_key == key))
    if previous is not None and (previous.tool != "universal_inventory" or previous.payload["binding"] != binding):
        raise Conflict("Ключ операции уже использован")
    return previous


async def equip(session, campaign_id, actor_id, item_id, equipped, request_key):
    if type(equipped) is not bool:
        raise ValueError("Нужен признак экипировки")
    async with session.begin_nested():
        await lock_campaign(session, campaign_id)
        await actor_row(session, campaign_id, actor_id)
        binding = dict(actor_id=actor_id, item_id=item_id, equipped=equipped)
        previous = await _previous(session, campaign_id, request_key, binding)
        if previous:
            return ActorDerived.model_validate(previous.payload["result"])
        await ensure_inventory(session, campaign_id, actor_id)
        _, row, state = await _owned(session, campaign_id, actor_id, item_id)
        if state.profile.kind == "consumable":
            raise ValueError("Расходник нельзя экипировать")
        if equipped:
            for other in await equipped_items(session, campaign_id, actor_id):
                other_state = state_of(other)
                if other_state.profile.kind == state.profile.kind:
                    other_state.equipped = False
                    store(other, other_state)
        state.equipped = equipped
        store(row, state)
        await session.flush()
        result = await actor_derived(session, campaign_id, actor_id)
        session.add(
            Event(
                campaign_id=campaign_id,
                actor_id=actor_id,
                tool="universal_inventory",
                idempotency_key=request_key,
                payload=dict(binding=binding, result=result.model_dump(mode="json")),
            )
        )
        await session.flush()
        return result


async def consume(session, campaign_id, actor_id, item_id, target_id, request_key):
    async with session.begin_nested():
        await lock_campaign(session, campaign_id)
        actor = await actor_row(session, campaign_id, actor_id)
        binding = dict(actor_id=actor_id, item_id=item_id, target_id=target_id)
        previous = await _previous(session, campaign_id, request_key, binding)
        if previous:
            return ExplorationOutcome.model_validate(previous.payload["result"]).model_copy(
                update={"status": "repeated"}
            )
        _, row, state = await _owned(session, campaign_id, actor_id, item_id)
        target = await actor_row(session, campaign_id, target_id)
        if target.location_id != actor.location_id or state.profile.kind != "consumable":
            raise AccessDenied("Цель или расходник недоступны")
        sheet, resources = await load_actor(session, campaign_id, target_id)
        maximum = (
            derive(sheet, []).hp_max
            if state.profile.restore_pool == "hp"
            else derive(sheet, []).energy_max[state.profile.restore_pool]
        )
        before = resources.hp if state.profile.restore_pool == "hp" else resources.energies[state.profile.restore_pool]
        after = min(maximum, before + state.profile.restore_amount)
        if state.profile.restore_pool == "hp":
            if resources_of(target).get("vitality", {}).get("state") == "dead":
                raise AccessDenied("Погибшего нельзя вылечить расходником")
            resources.hp = after
        else:
            resources.energies[state.profile.restore_pool] = after
        await save_actor(session, campaign_id, target_id, sheet, resources)
        if state.profile.restore_pool == "hp":
            from app.core.universal.vitality import enter_zero_hp

            await enter_zero_hp(session, campaign_id, target_id, request_key, 0)
        state.quantity -= 1
        store(row, state)
        result = ExplorationOutcome(
            success=True,
            changes=[
                EffectChange(
                    kind="item_consumed",
                    subject_id=target_id,
                    description=f"{state.profile.name}: восстановлено {after - before}.",
                    data=dict(item_id=item_id, pool=state.profile.restore_pool, restored=str(after - before)),
                )
            ],
        )
        session.add(
            Event(
                campaign_id=campaign_id,
                actor_id=actor_id,
                tool="universal_inventory",
                idempotency_key=request_key,
                payload=dict(binding=binding, result=result.model_dump(mode="json")),
            )
        )
        await session.flush()
        return result
