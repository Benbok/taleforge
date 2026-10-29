"""The turn's pause for an energy investment: roll first, offer, wait, and tell the resolver what was decided."""

import asyncio

from app.core.universal.investment import await_decision, make_offer, settle_offer
from app.db.models import MasterTurn
from app.gateway.events import publish_message
from app.rules.universal.investment import INVEST_TIMEOUT_SECONDS
from app.rules.universal.profiles import resolve_check

SETTLED = ("invested", "declined", "none")


async def _persist(service, turn_id, trace):
    async with service.maker() as s:
        (await s.get(MasterTurn, turn_id)).trace = dict(trace)
        await s.commit()


async def decide_investment(service, campaign, game_id, turn_id, trace, compiled, mid, sheet, resources, seat_id):
    """(rolls, invest) for the resolver. rolls is None when the action is not a check and nothing is pre-rolled.

    The die is rolled once and kept in the trace, so a restart replays the same roll; a decision already
    saved there is reused, and an offer that was still open is simply offered again."""
    proposal = compiled.proposal
    if getattr(compiled, "schema_version", None) != 2 or proposal.resolution != "check":
        return None, False
    rolls = trace.setdefault("rolls", {})
    decisions = trace.setdefault("investment", {})
    if mid not in rolls:
        score = getattr(sheet.abilities, proposal.attribute)
        rolls[mid] = resolve_check(service.dice_factory(), score, False, proposal.difficulty, proposal.edge).rolls
        await _persist(service, turn_id, trace)
    stored = tuple(rolls[mid])
    if decisions.get(mid) in SETTLED:
        return stored, decisions[mid] == "invested"
    async with service.maker() as s:
        message = await make_offer(
            s, campaign.id, game_id, turn_id, proposal, sheet, resources, stored, trace.get("audience"), seat_id
        )
        await s.commit()
    if message is None:
        decisions[mid] = "none"
        await _persist(service, turn_id, trace)
        return stored, False
    decisions[mid] = "offered"
    await _persist(service, turn_id, trace)
    # the answer slot opens before the card is shown, so a quick click cannot find the offer closed
    waiting = asyncio.create_task(
        await_decision(service, campaign.id, mid, getattr(service, "investment_timeout", INVEST_TIMEOUT_SECONDS))
    )
    await asyncio.sleep(0)
    await publish_message(service.bus, message)
    invest = await waiting
    status = "invested" if invest else "declined"
    async with service.maker() as s:
        message = await settle_offer(s, message.id, status)
        await s.commit()
    await publish_message(service.bus, message)
    decisions[mid] = status
    await _persist(service, turn_id, trace)
    return stored, invest
