"""Campaign-scoped universal actor and immutable profile persistence."""

from __future__ import annotations

from pydantic import Field, model_validator
from sqlalchemy import select

from app.core.campaigns import Conflict, NotFound
from app.db.models import Character, Entity, RuntimeProfile
from app.rules.universal.contracts import ENERGY_KEYS, ClosedModel, Count, EnergyKey, UniversalSheet
from app.rules.universal.mechanics import derive, starting_defense_bonuses
from app.rules.universal.profiles import EffectSpec, ProfileSpec, validate_profile


class ActorResources(ClosedModel):
    hp: Count
    energies: dict[EnergyKey, Count]
    effects: list[EffectSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def complete(self):
        if set(self.energies) != set(ENERGY_KEYS):
            raise ValueError("all five energy pools are required")
        return self


async def actor_row(session, campaign_id, actor_id, *, refresh=False):
    row = await session.scalar(
        select(Character)
        .where(Character.id == actor_id, Character.campaign_id == campaign_id)
        .execution_options(populate_existing=refresh)
    )
    if row is None:
        row = await session.scalar(
            select(Entity)
            .where(Entity.id == actor_id, Entity.campaign_id == campaign_id)
            .execution_options(populate_existing=refresh)
        )
    if row is None:
        raise NotFound("actor does not belong to campaign")
    return row


async def load_actor(session, campaign_id, actor_id):
    row = await actor_row(session, campaign_id, actor_id)
    data = row.sheet if isinstance(row, Character) else row.state.get("universal_sheet")
    data = dict(data or {})
    data.pop("source_library_id", None)
    sheet = UniversalSheet.model_validate(data)
    stored = row.resources if isinstance(row, Character) else row.state.get("resources", {})
    derived = derive(sheet, starting_defense_bonuses(sheet))
    resources = ActorResources.model_validate(
        dict(
            hp=stored.get("hp", derived.hp_max),
            energies=stored.get("energies", derived.energy_max),
            effects=stored.get("effects", []),
        )
    )
    if resources.hp > derived.hp_max or any(resources.energies[k] > derived.energy_max[k] for k in ENERGY_KEYS):
        raise ValueError("resources exceed derived maximum")
    return sheet, resources


async def save_actor(session, campaign_id, actor_id, sheet, resources):
    sheet = UniversalSheet.model_validate(sheet)
    resources = ActorResources.model_validate(resources)
    derived = derive(sheet, starting_defense_bonuses(sheet))
    if resources.hp > derived.hp_max or any(resources.energies[k] > derived.energy_max[k] for k in ENERGY_KEYS):
        raise ValueError("resources exceed derived maximum")
    row = await actor_row(session, campaign_id, actor_id)
    if isinstance(row, Character):
        row.sheet = {
            **({"source_library_id": row.sheet["source_library_id"]} if "source_library_id" in row.sheet else {}),
            **sheet.model_dump(mode="json"),
        }
        row.resources = {**row.resources, **resources.model_dump(mode="json")}
    else:
        row.state = {
            **row.state,
            "universal_sheet": sheet.model_dump(mode="json"),
            "resources": resources.model_dump(mode="json"),
        }


async def get_profile(session, campaign_id, ref, revision):
    row = await session.get(RuntimeProfile, (campaign_id, ref, int(revision)))
    if row is None:
        raise NotFound("profile not admitted in this campaign and revision")
    return ProfileSpec.model_validate(row.definition)


async def put_profile(session, campaign_id, profile):
    profile = validate_profile(profile)
    row = await session.get(RuntimeProfile, (campaign_id, profile.id, profile.revision))
    definition = profile.model_dump(mode="json")
    if row is not None:
        if row.definition != definition:
            raise Conflict("profile revision is immutable")
        return profile
    session.add(
        RuntimeProfile(
            campaign_id=campaign_id, ref=profile.id, revision=profile.revision, kind=profile.kind, definition=definition
        )
    )
    await session.flush()
    return profile


def actor_view(sheet, resources, private=False):
    return dict(
        sheet=sheet.model_dump(mode="json"),
        resources=resources.model_dump(mode="json"),
        derived=derive(sheet, starting_defense_bonuses(sheet)).model_dump(mode="json"),
    )
