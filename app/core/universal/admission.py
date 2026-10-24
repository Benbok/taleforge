"""World-aware, explicitly confirmed admission of independent library copies."""

from sqlalchemy import select, update

from app.core.campaigns import Conflict
from app.core.universal.editing import editable_sheet
from app.db.models import CampaignSecret, HeroDialogue, LibraryCharacter


async def world_context(session, campaign_id):
    if not campaign_id:
        return None
    secret = await session.get(CampaignSecret, campaign_id)
    fields = dict((secret.setting or {}).get("studio") or {}) if secret else {}
    # Guidance is returned directly to the player: never provide plot/history secrets.
    return {key: value for key, value in fields.items() if key not in ("secret_text", "history")} or None


async def start_admission(session, viewer, original, *, llm):
    from app.core.universal.creation import _campaign_target, answer_dialogue

    await _campaign_target(session, viewer.user.id, viewer.campaign.id, None)
    sheet = editable_sheet(original)
    draft = HeroDialogue(
        owner_user_id=viewer.user.id,
        campaign_id=viewer.campaign.id,
        target_id=original.id,
        description=sheet.description.model_dump(),
        transcript=[
            dict(
                role="system",
                content="Adapt only this campaign copy; preserve starting scores and equipment.",
                source_revision=original.revision,
            )
        ],
    )
    session.add(draft)
    await session.commit()
    return await answer_dialogue(session, draft.id, viewer.user.id, draft.revision, "", llm=llm)


async def admission_source(session, draft):
    # A conditional write also serializes confirmation against library edits. No lock
    # survives a model call; answer_dialogue reacquires this guard after guidance.
    locked = await session.scalar(
        update(LibraryCharacter)
        .where(
            LibraryCharacter.id == draft.target_id,
            LibraryCharacter.owner_user_id == draft.owner_user_id,
            LibraryCharacter.revision == draft.transcript[0].get("source_revision"),
        )
        .values(revision=LibraryCharacter.revision)
        .returning(LibraryCharacter.id)
        .execution_options(synchronize_session=False)
    )
    if locked is None:
        raise Conflict("Library hero changed; restart admission.")
    original = await session.scalar(
        select(LibraryCharacter).where(LibraryCharacter.id == locked).execution_options(populate_existing=True)
    )
    return editable_sheet(original)


async def admit_copy(session, library_id, campaign_id, seat_id):
    """Never silently admit an unreviewed library hero into an authored world."""
    from sqlalchemy import select

    from app.db.models import Character

    hero = await session.scalar(
        select(Character).where(Character.campaign_id == campaign_id, Character.seat_id == seat_id)
    )
    if hero and (hero.sheet or {}).get("source_library_id") == library_id:
        return hero
    raise Conflict("Review the campaign adaptation and explicitly confirm it before joining.")
