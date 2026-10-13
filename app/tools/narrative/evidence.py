"""Verify player-action provenance from durable resolution records.

No narrative author can supply these fields. Missing legacy provenance grants
no thread activation; player identity and targets come from saved requests.
"""

from collections.abc import Mapping

from pydantic import ValidationError

from app.core.narrative.contracts import EvidenceRef
from app.core.resolution.contracts import ActionRef, ResolutionResult
from app.db.models import Event, Message
from app.tools.registry import ToolContext


def action_message_id(event: Event) -> str | None:
    """Find the candidate source; the candidate still needs full verification."""
    if event.tool != "resolve_action":
        return None
    payload = event.payload if isinstance(event.payload, dict) else {}
    try:
        ref = ActionRef.model_validate(payload.get("ref"))
    except ValidationError:
        return None
    if ref.campaign_id != event.campaign_id or ref.source_kind != "message":
        return None
    return ref.source_id


def verified_player_action(
    ctx: ToolContext,
    event: Event,
    messages: Mapping[str, Message],
) -> tuple[EvidenceRef | None, tuple[str, ...]]:
    """Match a receipt or ordinary tool event to one completed player action."""
    if event.campaign_id != ctx.campaign.id or not event.actor_id:
        return None, ()
    hero = ctx.world.characters.get(event.actor_id)
    if hero is None or not hero.seat_id:
        return None, ()
    source_id = action_message_id(event)
    candidates = (
        (messages[source_id],)
        if source_id in messages
        else (() if event.tool == "resolve_action" else messages.values())
    )
    for message in candidates:
        if message.campaign_id != event.campaign_id or message.kind != "action" or message.seat_id != hero.seat_id:
            continue
        data = message.data if isinstance(message.data, dict) else {}
        bound = data.get("resolution_actions")
        completed = data.get("resolution_completed")
        if not isinstance(bound, list) or not isinstance(completed, dict):
            continue
        for part, item in enumerate(bound):
            if not isinstance(item, dict) or not isinstance(item.get("action"), dict):
                continue
            try:
                ref = ActionRef.model_validate(item.get("ref"))
                result = ResolutionResult.model_validate(completed.get(str(part)))
            except ValidationError:
                continue
            if (
                ref.campaign_id != event.campaign_id
                or ref.source_kind != "message"
                or ref.source_id != message.id
                or ref.actor_id != hero.id
                or ref.part != part
                or result.execution not in ("applied", "repeated")
            ):
                continue
            if event.tool == "resolve_action":
                payload = event.payload if isinstance(event.payload, dict) else {}
                try:
                    receipt_ref = ActionRef.model_validate(payload.get("ref"))
                    receipt = ResolutionResult.model_validate(payload.get("resolution"))
                except ValidationError:
                    continue
                if receipt_ref != ref or receipt.execution != "applied" or part not in receipt.completed_parts:
                    continue
            elif event.id not in result.event_ids:
                continue
            action = item["action"]
            targets = tuple(
                dict.fromkeys(
                    t
                    for t in (action.get("target_id"), *(action.get("target_ids") or []))
                    if isinstance(t, str) and t and t != hero.id
                )
            )
            return EvidenceRef(campaign_id=event.campaign_id, kind="message", source_id=message.id), targets
    return None, ()
