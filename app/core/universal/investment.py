"""The pause after a failed check: the offer to buy a small shortfall with the attribute's energy, and its answer."""

import asyncio
import time
from dataclasses import dataclass
from typing import Literal

from app.core.chat import next_seq
from app.core.universal.combat_actions import COMBAT_KINDS
from app.db.models import Message
from app.rules.dice import FixedDice
from app.rules.universal.investment import INVEST_MAX_SHORTFALL, INVEST_TIMEOUT_SECONDS, invest_price, shortfall
from app.rules.universal.profiles import resolve_check


@dataclass(frozen=True)
class OfferTerms:
    attribute: str
    natural: int
    modifier: int
    total: int
    difficulty: int
    shortfall: int
    price: int
    available: int


def evaluate_offer(action, sheet, resources, rolls) -> OfferTerms | None:
    """The terms of an offer, or None when no pause is warranted; the server alone decides, from the stored roll."""
    if action.resolution != "check" or any(op.kind in COMBAT_KINDS for op in action.operations):
        return None
    pool = resources.energies.get(action.attribute)
    if pool is None:  # constitution has no pool to invest
        return None
    check = resolve_check(
        FixedDice(list(rolls)), getattr(sheet.abilities, action.attribute), False, action.difficulty, action.edge
    )
    missed = shortfall(check.natural, check.total, action.difficulty)
    if not 1 <= missed <= INVEST_MAX_SHORTFALL:
        return None
    price = invest_price(missed, sheet.level)
    if pool - action.cost < price:
        return None
    return OfferTerms(
        action.attribute,
        check.natural,
        check.total - check.natural,
        check.total,
        action.difficulty,
        missed,
        price,
        pool,
    )


async def make_offer(session, campaign_id, session_id, turn_id, action, sheet, resources, rolls, audience, seat_id):
    terms = evaluate_offer(action, sheet, resources, rolls)
    if terms is None:
        return None
    deadline = int(time.time()) + INVEST_TIMEOUT_SECONDS
    existing = await session.get(Message, "invest_" + action.source_message_id)
    if existing is not None:  # the turn restarted while the card was open: the same card, a fresh deadline
        existing.data = {**existing.data, "status": "offered", "deadline_ts": deadline}
        await session.flush()
        return existing
    message = Message(
        id="invest_" + action.source_message_id,
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        seq=await next_seq(session, campaign_id),
        kind="investment",
        visible_to=audience,
        content="Вложить усилие?",
        data=dict(
            mid=action.source_message_id,
            actor_id=action.actor_id,
            seat_id=seat_id,
            status="offered",
            deadline_ts=deadline,
            **{key: getattr(terms, key) for key in terms.__dataclass_fields__},
        ),
    )
    session.add(message)
    await session.flush()
    return message


async def settle_offer(session, message_id, status: Literal["invested", "declined", "expired"]) -> Message:
    message = await session.get(Message, message_id)
    message.data = {**message.data, "status": status}
    await session.flush()
    return message


async def await_decision(service, campaign_id, mid, timeout=INVEST_TIMEOUT_SECONDS) -> bool:
    """True when the player invests; silence, a refusal or a cancelled turn all leave the roll as it fell."""
    future = asyncio.get_running_loop().create_future()
    service.investments[(campaign_id, mid)] = future
    try:
        return await asyncio.wait_for(future, timeout)
    except TimeoutError:
        return False
    finally:
        service.investments.pop((campaign_id, mid), None)


def submit_decision(service, campaign_id, mid, accept: bool) -> bool:
    """False when no offer is open or it was already answered: the first answer wins."""
    future = service.investments.get((campaign_id, mid))
    if future is None or future.done():
        return False
    future.set_result(bool(accept))
    return True
