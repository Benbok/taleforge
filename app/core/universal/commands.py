"""Orders to a being the hero made: free to give, judged by the master against what the being can do."""

from app.core.campaigns import AccessDenied
from app.core.universal.objects import accessible, object_state
from app.db.models import Character, Entity
from app.rules.universal.exploration import EffectChange


async def command_creature(ctx, op, source_event):
    """Record an order from the creator to a live created being. Nothing is paid and nothing is decided here:
    whether the being can do it is the master's judgement from its description and the world's laws."""
    s = ctx.session
    actor = await s.get(Character, ctx.actor_id)
    row = await s.get(Entity, op.object_id or "")
    try:
        accessible(row, actor)
    except AccessDenied:
        raise ValueError("Существа больше нет: оно рассыпалось или далеко") from None
    state = object_state(row)
    if state.template != "creature":
        raise ValueError("Приказывать можно только созданному существу")
    if state.controller_id != actor.id:
        raise ValueError("Приказывать может только создатель")
    order = op.label or "действовать"
    return EffectChange(
        kind="commanded",
        subject_id=row.id,
        description=f"{row.name} получает приказ: {order}.",
        data={"order": order, "abilities": state.abilities},
    )
