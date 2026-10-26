from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.campaigns import NotFound
from app.core.universal.portraits import portrait_url
from app.db.models import LibraryCharacter
from app.rules.universal.mechanics import starting_defense_bonuses, starting_items


async def load_library_hero(session: AsyncSession, owner_id: str, hero_id: str) -> LibraryCharacter:
    hero = await session.scalar(
        select(LibraryCharacter).where(
            LibraryCharacter.id == hero_id,
            LibraryCharacter.owner_user_id == owner_id,
        )
    )
    if hero is None:
        raise NotFound("герой не найден")
    return hero


def card_of(hero: LibraryCharacter) -> dict:
    from app.rules.universal.contracts import HeroCard, UniversalSheet
    from app.rules.universal.mechanics import derive

    sheet = UniversalSheet.model_validate(hero.sheet)
    derived = derive(sheet, starting_defense_bonuses(sheet))
    return HeroCard(
        id=hero.id,
        name=sheet.description.name or hero.name,
        portrait_url=portrait_url(hero.portrait_id),
        revision=hero.revision,
        level=sheet.level,
        sheet=sheet,
        derived=derived,
        hp=derived.hp_max,
        energies=derived.energy_max,
        equipment=starting_items(sheet),
    ).model_dump(mode="json")


async def hero_card(session: AsyncSession, owner_id: str, hero_id: str) -> dict:
    return card_of(await load_library_hero(session, owner_id, hero_id))


def game_card_of(hero, *, learned=None) -> dict:
    from app.rules.universal.contracts import UniversalGameCard, UniversalSheet
    from app.rules.universal.mechanics import derive

    data = dict(hero.sheet)
    data.pop("source_library_id", None)
    sheet = UniversalSheet.model_validate(data)
    derived = derive(sheet, starting_defense_bonuses(sheet))
    saved_abilities = (hero.resources or {}).get("learned_abilities", []) if learned is None else learned
    learned = []
    for item in saved_abilities:
        view = dict(item)
        if (item.get("profile") or {}).get("schema_version") == 2:
            from app.rules.universal.exploration import AbilityDefinitionV2, exploration_cost

            definition = AbilityDefinitionV2.model_validate(item["profile"])
            view.update(
                description=definition.name,
                cost=str(exploration_cost(definition, sheet.level)),
                resource_key=definition.attribute,
                limits=dict(
                    targets=str(definition.target_count),
                    duration=str(definition.duration_seconds),
                    intensity=definition.intensity,
                    conditions=[],
                ),
            )
            learned.append(view)
            continue
        if item.get("profile"):
            from app.rules.universal.profiles import ProfileSpec, resource_cost

            profile = ProfileSpec.model_validate(item["profile"])
            view.update(
                description=item.get("description") or item.get("name", ""),
                cost=str(resource_cost(profile, sheet.level)),
                resource_key=profile.resource_key or (profile.attribute if profile.attribute != "con" else None),
                limits={
                    "targets": str(profile.target_count),
                    "duration": str(profile.duration),
                    "intensity": profile.intensity,
                    "conditions": profile.use_conditions,
                },
            )
        learned.append(view)
    from app.rules.universal.progression import level_threshold

    floor, ceiling = level_threshold(sheet.level), level_threshold(sheet.level + 1)
    progress = dict(
        admission_pending=bool(hero.resources.get("admission_pending")),
        current_threshold=str(floor),
        next_threshold=str(ceiling),
        xp_to_next=str(max(0, ceiling - sheet.xp)),
        percent=str(min(100, max(0, sheet.xp - floor) * 100 // (ceiling - floor))),
    )
    return UniversalGameCard(
        progression=progress,
        id=hero.id,
        name=hero.name,
        portrait_url=portrait_url(hero.portrait_id),
        revision=int(hero.resources.get("progression_revision", 1)),
        level=sheet.level,
        sheet=sheet,
        derived=derived,
        hp=hero.resources.get("hp", derived.hp_max),
        energies=hero.resources.get("energies", derived.energy_max),
        seat_id=hero.seat_id,
        status=hero.status,
        equipment=starting_items(sheet),
        learned_abilities=learned,
    ).model_dump(mode="json")
