"""Link only public scene references; narration cannot mint access to hidden entities."""

from sqlalchemy import select

from app.core.linker import MARKUP, autolink
from app.db.models import MasterTurn


def scene_names(scene):
    rows = [scene.get("location") or {}, *scene.get("entities", []), *scene.get("heroes", [])]
    return {row["id"]: row["name"] for row in rows if row.get("id") and row.get("name")}


def link_scene_text(text, scene):
    names = scene_names(scene)
    text = MARKUP.sub(lambda match: match.group(0) if match.group(1) in names else match.group(2), text)
    return autolink(text, names)


def location_reference(scene):
    place = scene.get("location") or {}
    return (
        {key: place[key] for key in ("id", "name", "description") if key in place}
        if place.get("id") and place.get("name")
        else None
    )


async def project_history(session, campaign, messages, payloads):
    """Enrich visible legacy messages without rewriting the chat or replaying any turn."""
    if campaign.ruleset_id != "universal" or not messages:
        return payloads
    ids = [message.id for message in messages if message.kind == "narration"]
    turns = await session.scalars(
        select(MasterTurn).where(
            MasterTurn.campaign_id == campaign.id,
            MasterTurn.narration_message_id.in_(ids),
        )
    )
    scenes = {turn.narration_message_id: (turn.trace or {}).get("scene", {}) for turn in turns}
    for payload in payloads:
        scene = scenes.get(payload["id"])
        if scene:
            payload["content"] = link_scene_text(payload["content"], scene)
            payload["data"] = {**(payload.get("data") or {}), "location_ref": location_reference(scene)}
            payload["scope"] = "party" if payload.get("whisper") else "public"
    return payloads
