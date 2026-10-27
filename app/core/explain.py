"""Owner/master stat explanations from the authoritative Universal profile and equipment."""

from sqlalchemy import select

from app.core.universal.inventory import actor_derived
from app.core.universal.profiles import load_actor
from app.db.models import Event
from app.rules.universal.contracts import ABILITY_KEYS


class ExplainError(ValueError):
    pass


async def hp_history(session, ch):
    events = await session.scalars(
        select(Event)
        .where(
            Event.campaign_id == ch.campaign_id,
            Event.actor_id == ch.id,
            Event.tool == "universal_action",
            Event.hidden.is_(False),
        )
        .order_by(Event.created_at.desc())
        .limit(8)
    )
    return list(reversed([e.payload.get("outcome", {}).get("description", "Действие сохранено.") for e in events]))


async def explain_for(session, ch, cat, stat):
    sheet, resources = await load_actor(session, ch.campaign_id, ch.id)
    derived = await actor_derived(session, ch.campaign_id, ch.id)
    if stat in {"hp", "hp_max"}:
        value = resources.hp if stat == "hp" else derived.hp_max
        return dict(
            stat=stat,
            label="Жизненные силы",
            value=str(value),
            parts=[dict(label="Максимум: 10 + CON + 6 × (уровень − 1)", value=str(derived.hp_max))],
            history=await hp_history(session, ch),
        )
    if stat == "ac":
        return dict(
            stat=stat,
            label="КД",
            value=str(derived.ac),
            parts=[
                dict(label="Основа", value="12"),
                dict(label="Ловкость", value=str(derived.modifiers["dex"])),
                dict(label="Надетая броня", value=str(derived.ac - 12 - derived.modifiers["dex"])),
            ],
        )
    key = stat.removeprefix("ability:")
    if key in ABILITY_KEYS:
        value = sheet.abilities.model_dump()[key]
        return dict(
            stat=stat,
            label=key.upper(),
            value=str(value),
            parts=[dict(label="Модификатор: (характеристика − 10) // 2", value=str(derived.modifiers[key]))],
        )
    raise ExplainError("Такой величины нет в универсальной карточке героя.")
