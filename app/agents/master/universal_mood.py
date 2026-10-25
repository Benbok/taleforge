"""Master temper from the cabinet, coloured by natural 20 and 1 results, as a tone note for the narration."""

from __future__ import annotations

import logging

from app.core.campaigns import master_seat
from app.db.models import AgentConfig, MasterTurn, Scene
from app.emotion import game as mood

log = logging.getLogger(__name__)


def mood_update(persona_id, state, outcomes):
    """Tone note and the next mood state. The temper sets the tone; natural 20/1 of this turn shift the mood."""
    persona = mood.persona_of(persona_id)
    applied = [o for o in outcomes.values() if o.get("status") == "applied"]
    successes = sum(1 for o in applied if o.get("critical") and not o.get("critical_failure"))
    failures = sum(1 for o in applied if o.get("critical_failure"))
    new = mood.step(mood.load({mood.MOOD_KEY: state}), persona, mood.crit_delta(persona, successes, failures))
    note = (
        f"Нрав мастера — {persona.name}: {persona.description} "
        "Окрашивай подачу этим нравом, но не меняй сохранённые факты, результаты и числа."
    )
    if extra := mood.instruction(new):
        note += "\n" + extra
    return note, mood.dump(new)


async def mood_note(service, campaign, tid, trace):
    """Computed once per turn: a restarted narration reuses the saved note and never steps the mood twice."""
    if "mood_note" in trace:
        return trace["mood_note"]
    try:
        async with service.maker() as s:
            seat = master_seat(campaign)
            cfg = await s.get(AgentConfig, seat.agent_config_id) if seat.agent_config_id else None
            scene = await s.get(Scene, campaign.id)
            note, state = mood_update(
                (cfg.settings or {}).get("emotion_persona") if cfg else None,
                ((scene.state or {}).get(mood.MOOD_KEY) if scene else None) or {},
                trace.get("outcomes", {}),
            )
            if scene is not None:
                scene.state = {**(scene.state or {}), mood.MOOD_KEY: state}
            trace["mood_note"] = note
            turn = await s.get(MasterTurn, tid)
            turn.trace = dict(trace)
            await s.commit()
        return note
    except Exception:  # noqa: BLE001 - tone is decoration; it must never stop the turn
        log.exception("master mood failed")
        return ""
