"""Bounded physical props. All mutations run inside the action transaction."""

import hashlib
from typing import Literal

from pydantic import Field
from sqlalchemy import select

from app.core.campaigns import AccessDenied
from app.core.universal.profiles import load_actor, save_actor
from app.db.models import Character, Entity
from app.rules.universal.contracts import ClosedModel, Count
from app.rules.universal.exploration import EffectChange, EffectIntentV2, IntroductionV2, Scale, Sturdiness
from app.rules.universal.mechanics import derive, starting_defense_bonuses


class ObjectState(ClosedModel):
    schema_version: Literal[2] = 2
    template: Literal["vessel", "wood_source", "water_source", "energy_tonic", "structure", "creature"]
    owner_id: str | None = None
    material: Literal["wood", "plant", "stone"] = "wood"
    amount: Count = 1
    capacity_ml: Count = Field(default=0, le=2000)
    contents_ml: Count = 0
    liquid: Literal["water"] = "water"
    temporary: bool = False
    expired: bool = False
    energy_pool: Literal["wis"] | None = None
    restore_amount: Count = Field(default=0, le=1)
    source_event_id: str | None = None
    scale: Scale = "tiny"
    sturdiness: Sturdiness = "ordinary"
    leads_to: str = Field(default="", max_length=128)
    leads_view: str = Field(default="", max_length=300)
    leads_to_location_id: str | None = None
    controller_id: str | None = None  # who gives a created being its orders
    abilities: str = Field(default="", max_length=500)


def object_state(row):
    return ObjectState.model_validate(row.state["exploration"])


def store(row, state):
    row.state = {**row.state, "exploration": state.model_dump(mode="json")}


def ordinary_object_view(entity):
    return dict(
        id=entity.id,
        name=entity.name,
        location_id=entity.location_id,
        **object_state(entity).model_dump(mode="json", exclude={"source_event_id", "leads_to_location_id"}),
    )


def accessible(row, actor, *, held=False):
    if row is None or row.campaign_id != actor.campaign_id or row.kind != "object":
        raise AccessDenied("Предмет недоступен")
    state = object_state(row)
    if (
        state.expired
        or state.amount < 1
        or row.state.get("hidden")
        or row.state.get("visibility") in {"hidden", "private"}
    ):
        raise AccessDenied("Предмет недоступен")
    if state.owner_id not in {None, actor.id} or (held and state.owner_id != actor.id):
        raise AccessDenied("Предмет не принадлежит герою")
    here = actor.location_id in {row.location_id, state.leads_to_location_id}  # both ends of a crossing
    if state.owner_id is None and not here:
        raise AccessDenied("Предмет находится в другом месте")
    return state


async def visible_objects(session, campaign_id, actor_id):
    actor = await session.get(Character, actor_id)
    if actor is None or actor.campaign_id != campaign_id:
        raise AccessDenied("Герой недоступен")
    result = []
    for row in await session.scalars(select(Entity).where(Entity.campaign_id == campaign_id, Entity.kind == "object")):
        if "exploration" not in row.state:
            continue
        try:
            accessible(row, actor)
        except AccessDenied:
            continue
        result.append(ordinary_object_view(row))
    return result


async def introduce_object(session, campaign_id, spec, evidence, *, actor_id):
    spec = IntroductionV2.model_validate(spec.model_dump())
    if spec.evidence_quote not in evidence or spec.template == "observer":
        raise ValueError("Нет подтверждения предмета в известных фактах")
    actor = await session.get(Character, actor_id)
    if actor is None or actor.campaign_id != campaign_id:
        raise AccessDenied("Неверная область предмета")
    # Identity depends on established evidence and place, never on model aliases.
    key = (
        "en_"
        + hashlib.sha256(
            f"{campaign_id}:{actor.location_id}:{spec.template}:{spec.evidence_quote}".encode()
        ).hexdigest()[:24]
    )
    row = await session.get(Entity, key)
    if row is not None:
        return row
    state = ObjectState(
        template=spec.template,
        amount=spec.amount if spec.template in {"wood_source", "water_source"} else 1,
        capacity_ml=300 if spec.template == "vessel" else 0,
        energy_pool="wis" if spec.template == "energy_tonic" else None,
        restore_amount=1 if spec.template == "energy_tonic" else 0,
    )
    row = Entity(
        id=key,
        campaign_id=campaign_id,
        kind="object",
        name=spec.name,
        description=spec.evidence_quote,
        location_id=actor.location_id,
        state={},
    )
    store(row, state)
    session.add(row)
    await session.flush()
    return row


async def apply_object_operation(ctx, operation, source_event, *, component="0"):
    op = EffectIntentV2.model_validate(operation.model_dump())
    s = ctx.session
    actor = await s.get(Character, ctx.actor_id)
    if (
        actor is None
        or actor.campaign_id != ctx.campaign_id
        or source_event.campaign_id != ctx.campaign_id
        or source_event.actor_id != actor.id
    ):
        raise AccessDenied("Неверная область операции")
    if op.kind == "create_object":
        if op.template not in {"vessel", "structure", "creature"} or op.quantity != 1:
            raise ValueError("Создаётся один предмет или одна постройка")
        key = "en_" + hashlib.sha256(f"{source_event.id}:{component}".encode()).hexdigest()[:24]
        row = await s.get(Entity, key)
        if row is None:
            if op.template in {"structure", "creature"}:
                # Anything the world's laws and the hero's strength allow; the place owns it, so others may use it.
                state = ObjectState(
                    template=op.template,
                    owner_id=None,
                    material=op.material,
                    temporary=True,  # whatever is made lasts only its term
                    source_event_id=source_event.id,
                    scale=op.scale,
                    sturdiness=op.sturdiness,
                    leads_to=op.leads_to,
                    leads_view=op.leads_view,
                    controller_id=actor.id if op.template == "creature" else None,
                    abilities=op.abilities,
                )
                row = Entity(
                    id=key,
                    campaign_id=ctx.campaign_id,
                    kind="object",
                    name=op.label or ("Существо" if op.template == "creature" else "Постройка"),
                    description=op.appearance,
                    location_id=actor.location_id,
                    state={},
                )
                store(row, state)
                s.add(row)
                await s.flush()
                return EffectChange(
                    kind="object_created",
                    subject_id=row.id,
                    description=f"Создано: {row.name}.",
                    data=ordinary_object_view(row),
                )
            if op.source_id:
                material = await s.get(Entity, op.source_id)
                source = accessible(material, actor)
                if source.template != "wood_source" or source.amount < 1 or op.material not in {"wood", "plant"}:
                    raise ValueError("Неподходящий материал")
                source.amount -= 1
                store(material, source)
            state = ObjectState(
                template="vessel",
                owner_id=actor.id,
                material=op.material,
                capacity_ml=op.capacity_ml,
                temporary=True,  # whatever is made lasts only its term
                source_event_id=source_event.id,
            )
            row = Entity(
                id=key,
                campaign_id=ctx.campaign_id,
                kind="object",
                name=op.label or "Кружка",
                description=op.appearance,
                location_id=actor.location_id,
                state={},
            )
            store(row, state)
            s.add(row)
        await s.flush()
        return EffectChange(
            kind="object_created",
            subject_id=row.id,
            description=f"Создан предмет: {row.name}.",
            data=ordinary_object_view(row),
        )
    if op.kind == "move":
        from app.core.universal.crossing import cross_structure

        return await cross_structure(ctx, op, source_event)
    if op.kind == "command":
        from app.core.universal.commands import command_creature

        return await command_creature(ctx, op, source_event)
    row = await s.get(Entity, op.object_id or "")
    state = accessible(row, actor, held=op.kind in {"give", "place", "fill", "pour", "empty", "consume"})
    data = {}
    if state.template in {"structure", "creature"} and op.kind in {"take", "give", "place", "fill", "pour", "empty"}:
        raise ValueError("Постройку или существо нельзя переносить, передавать или наполнять")
    if op.kind == "take":
        state.owner_id = actor.id
    elif op.kind == "place":
        state.owner_id = None
        row.location_id = actor.location_id
    elif op.kind == "give":
        recipient = await s.get(Character, op.recipient_id or "")
        if recipient is None or recipient.campaign_id != ctx.campaign_id or recipient.location_id != actor.location_id:
            raise AccessDenied("Получатель недоступен")
        state.owner_id = recipient.id
        row.location_id = recipient.location_id
    elif op.kind in {"fill", "pour"}:
        other = await s.get(Entity, (op.source_id if op.kind == "fill" else op.target_id) or "")
        other_state = accessible(other, actor)
        if row.id == other.id:
            raise ValueError("Нужны разные сосуды")
        src, dst = (other_state, state) if op.kind == "fill" else (state, other_state)
        if dst.template != "vessel" or src.template not in {"vessel", "water_source"}:
            raise ValueError("Нельзя перелить жидкость")
        available = src.amount if src.template == "water_source" else src.contents_ml
        if op.amount > available or dst.contents_ml + op.amount > dst.capacity_ml:
            raise ValueError("Недостаточно жидкости или места в сосуде")
        if src.template == "water_source":
            src.amount -= op.amount
        else:
            src.contents_ml -= op.amount
        dst.contents_ml += op.amount
        store(other, other_state)
        data["transferred_ml"] = str(op.amount)
    elif op.kind == "empty":
        if state.template != "vessel":
            raise ValueError("Это не сосуд")
        data["released_ml"] = str(state.contents_ml)
        state.contents_ml = 0
    elif op.kind == "consume":
        if state.template == "energy_tonic":
            sheet, resources = await load_actor(s, ctx.campaign_id, actor.id)
            maximum = derive(sheet, starting_defense_bonuses(sheet)).energy_max[state.energy_pool]
            before = resources.energies[state.energy_pool]
            resources.energies[state.energy_pool] = min(maximum, before + state.restore_amount)
            await save_actor(s, ctx.campaign_id, actor.id, sheet, resources)
            state.amount -= 1
            data = dict(energy_pool=state.energy_pool, restored=str(resources.energies[state.energy_pool] - before))
        elif state.template == "vessel" and state.contents_ml >= op.amount:
            state.contents_ml -= op.amount
            data["drunk_ml"] = str(op.amount)
        else:
            raise ValueError("Предмет нельзя употребить")
    else:
        raise ValueError("Неизвестная операция с предметом")
    store(row, state)
    await s.flush()
    return EffectChange(
        kind=f"object_{op.kind}",
        subject_id=row.id,
        description=f"{row.name}: действие выполнено.",
        data={**ordinary_object_view(row), **data},
    )


async def expire_temporary_object(session, campaign_id, object_id):
    row = await session.get(Entity, object_id)
    if row is None or row.campaign_id != campaign_id:
        raise AccessDenied("Неверная область предмета")
    state = object_state(row)
    if state.expired or not state.temporary:
        return []
    released = state.contents_ml
    state.contents_ml = 0
    state.expired = True
    store(row, state)
    # Released water persists as an ordinary source at the holder's current location.
    holder = await session.get(Character, state.owner_id) if state.owner_id else None
    if released:
        spill = Entity(
            id="en_" + hashlib.sha256(f"release:{row.id}".encode()).hexdigest()[:24],
            campaign_id=campaign_id,
            kind="object",
            name="Разлитая вода",
            description="Вода из исчезнувшего сосуда.",
            location_id=holder.location_id if holder else row.location_id,
            state={},
        )
        store(spill, ObjectState(template="water_source", amount=released))
        session.add(spill)
    await session.flush()
    return [
        EffectChange(
            kind="object_expired",
            subject_id=row.id,
            description=(
                f"{row.name} рассыпается: срок вышел."
                if state.template == "creature"
                else f"{row.name} исчезает; содержимое остаётся."
            ),
            data={"released_ml": str(released)},
        )
    ]
