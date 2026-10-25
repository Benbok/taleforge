"""Immutable V2 definitions use the existing campaign profile registry."""

from app.core.campaigns import Conflict, NotFound
from app.db.models import RuntimeProfile
from app.rules.universal.exploration import AbilityDefinitionV2, definition_key


async def admit_definition(session, campaign_id, definition):
    definition = AbilityDefinitionV2.model_validate(definition.model_dump())
    key = definition_key(definition)
    if definition.id and definition.id != key:
        raise Conflict("Definition identity does not match its effects")
    definition.id = key
    row = await session.get(RuntimeProfile, (campaign_id, key, definition.revision))
    if row is not None:
        if row.kind != "exploration":
            raise Conflict("Profile kind changed")
        saved = AbilityDefinitionV2.model_validate(row.definition)
        if definition_key(saved) != key:
            raise Conflict("Immutable ability definition changed")
        return saved
    session.add(
        RuntimeProfile(
            campaign_id=campaign_id,
            ref=key,
            revision=definition.revision,
            kind="exploration",
            definition=definition.model_dump(mode="json"),
        )
    )
    await session.flush()
    return definition


async def load_definition(session, campaign_id, ref, revision):
    row = await session.get(RuntimeProfile, (campaign_id, ref, int(revision)))
    if row is None or row.kind != "exploration":
        raise NotFound("Ability definition is not admitted in this campaign")
    return AbilityDefinitionV2.model_validate(row.definition)
