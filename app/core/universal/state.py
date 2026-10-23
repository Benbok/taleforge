from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.campaigns import NotFound
from app.core.universal.portraits import portrait_url
from app.db.models import LibraryCharacter


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
    derived = derive(sheet, [])
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
    ).model_dump(mode="json")


async def hero_card(session: AsyncSession, owner_id: str, hero_id: str) -> dict:
    return card_of(await load_library_hero(session, owner_id, hero_id))


def game_card_of(hero) -> dict:
    from app.rules.universal.contracts import UniversalGameCard, UniversalSheet
    from app.rules.universal.mechanics import derive

    data = dict(hero.sheet)
    data.pop("source_library_id", None)
    sheet = UniversalSheet.model_validate(data)
    derived = derive(sheet, [])
    return UniversalGameCard(
        id=hero.id,
        name=hero.name,
        portrait_url=portrait_url(hero.portrait_id),
        revision=1,
        level=sheet.level,
        sheet=sheet,
        derived=derived,
        hp=hero.resources.get("hp", derived.hp_max),
        energies=hero.resources.get("energies", derived.energy_max),
        seat_id=hero.seat_id,
        status=hero.status,
    ).model_dump(mode="json")
