"""Replay-safe public roll evidence, projected exclusively from committed-action receipts."""

from sqlalchemy import select

from app.core.chat import next_seq
from app.core.rolls import ABILITY_RU
from app.core.universal.contracts import ProposedAction
from app.db.models import Character, Entity, Event, Message
from app.rules.universal.profiles import ActionOutcome


async def ensure_roll_message(session, campaign_id, session_id, turn_id, source_id, audience):
    event = await session.scalar(
        select(Event).where(
            Event.campaign_id == campaign_id,
            Event.idempotency_key == source_id,
            Event.tool == "universal_action",
        )
    )
    if event is None or event.hidden:
        return None
    message_id = "roll_" + event.id
    existing = await session.get(Message, message_id)
    if existing is not None:
        return existing
    v2 = event.payload.get("schema_version") == 2
    if v2:
        from app.rules.universal.exploration import ExplorationAction, ExplorationOutcome

        proposal = ExplorationAction.model_validate(event.payload["proposal"])
        result = ExplorationOutcome.model_validate(event.payload["outcome"])
    else:
        proposal = ProposedAction.model_validate(event.payload["proposal"])
        result = ActionOutcome.model_validate(event.payload["outcome"])
    if not result.rolls and not v2:
        return None
    checks = [check.model_dump(mode="json") for check in result.checks]
    for check in checks:
        target = await session.get(Character, check["target_id"])
        # Opponent armor remains private; the saved result still proves hit/miss.
        if check["kind"] == "attack" and (target is None or not target.seat_id):
            check["difficulty"] = None
        check["target_name"] = target.name if target else "Цель"
    actor = await session.get(Character, event.actor_id) or await session.get(Entity, event.actor_id)
    proof = dict(
        receipt_id=event.id,
        source_id=source_id,
        revision=str(proposal.definition.revision if v2 else proposal.ref.revision),
        checks=checks,
        draws=[draw.model_dump() for draw in result.draws],
        cost=str(result.cost),
        damage=str(result.damage),
        resource_key=(proposal.attribute if proposal.cost else None) if v2 else proposal.profile.resource_key,
        legacy=not bool(result.draws) and not v2,
        description=result.description,
    )
    # Old receipts keep their original flat draws; never invent missing die sizes or per-target checks.
    if proof["legacy"]:
        proof["legacy_draws"] = result.rolls
        if result.natural is not None:
            proof["legacy_total"] = str(result.total)
    if v2:
        proof.update(
            source_kind=proposal.definition.source,
            automatic=proposal.resolution == "automatic",
            changes=[c.model_dump(mode="json") for c in result.changes if not c.private],
            ability_ref=result.ability_ref,
            game_seconds=str(result.game_seconds),
        )
        title = proposal.definition.name
    else:
        title = (
            f"{'Атака' if proposal.profile.kind == 'damage' else 'Проверка'}: {ABILITY_RU[proposal.profile.attribute]}"
        )
        if proposal.profile.kind == "heal":
            title = "Исцеление"
    data = dict(
        tool="universal_action",
        title=title,
        who=actor.name if actor else None,
        outcome=(
            "crit_success"
            if result.success and result.critical
            else "crit_fail"
            if not result.success and result.critical_failure
            else "success"
            if result.success
            else "fail"
        ),
        universal_proof=proof,
    )
    outcome_word = {
        "crit_success": "критический успех",
        "crit_fail": "критический провал",
        "success": "успех",
        "fail": "провал",
    }[data["outcome"]]
    message = Message(
        id=message_id,
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        seq=await next_seq(session, campaign_id),
        kind="roll",
        visible_to=audience,
        content=f"{title}: {outcome_word}",
        data=data,
    )
    session.add(message)
    await session.flush()
    return message


async def ensure_completion_message(session, campaign_id, session_id, turn_id, source_id, audience):
    from types import SimpleNamespace

    from app.core.universal.effects import scope_changes
    from app.db.models import CombatExchange
    from app.rules.universal.exploration import EffectChange

    exchange = await session.scalar(
        select(CombatExchange).where(CombatExchange.campaign_id == campaign_id, CombatExchange.source_key == source_id)
    )
    if exchange is None or exchange.status != "ticks_done":
        return None
    mid = "tick_" + exchange.id
    existing = await session.get(Message, mid)
    if existing:
        return existing
    scoped = await scope_changes(
        SimpleNamespace(session=session, campaign_id=campaign_id, actor_id=exchange.actor_id),
        [EffectChange.model_validate(change) for change in exchange.changes],
    )
    changes = [change for change in scoped if not change.private]
    if not changes:
        return None
    draws = [draw for change in changes for draw in change.data.get("draws", [])]
    proof = dict(
        receipt_id=exchange.id,
        source_id=source_id,
        revision="2",
        cost="0",
        damage=str(sum(int(change.data.get("amount", "0")) for change in changes if change.kind == "periodic_damage")),
        resource_key=None,
        draws=draws,
        checks=[],
        legacy=False,
        automatic=True,
        description=" ".join(change.description for change in changes),
        changes=[change.model_dump(mode="json") for change in changes],
    )
    message = Message(
        id=mid,
        campaign_id=campaign_id,
        session_id=session_id,
        turn_id=turn_id,
        seq=await next_seq(session, campaign_id),
        kind="roll",
        visible_to=audience,
        content="Последствия игрового шага",
        data=dict(tool="universal_action", title="Последствия шага", outcome="success", universal_proof=proof),
    )
    session.add(message)
    await session.flush()
    return message
