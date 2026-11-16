"""Разовый перенос: герои, созданные игроками в кампаниях до сохранения в библиотеку, получают копию в библиотеке.

    python tools/backfill_library_heroes.py           # только показать, кого перенесёт
    python tools/backfill_library_heroes.py --apply   # перенести

Копия — базовый герой первого уровня: исходные характеристики, описание и стартовое снаряжение; развитие в
кампании в библиотеку не переносится. Портрет переносится, если его создал сам игрок. Игровой герой получает
связь source_library_id, поэтому повторный запуск его уже не трогает.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.db.models import Character, HeroPortrait, LibraryCharacter, Seat, new_id
from app.rules.universal.contracts import HeroBudget, UniversalSheet


def base_sheet(sheet: dict) -> UniversalSheet:
    data = dict(sheet)
    data.pop("source_library_id", None)
    played = UniversalSheet.model_validate(data)
    scores = played.budget.initial_scores if played.budget else played.abilities
    return UniversalSheet(
        abilities=scores,
        description=played.description,
        budget=HeroBudget(initial_scores=scores),
        starting_equipment=played.starting_equipment,
    )


async def candidates(session) -> list[Character]:
    rows = (
        await session.scalars(
            select(Character)
            .join(Seat, Seat.id == Character.seat_id)
            .where(
                Character.owner_user_id.is_not(None),
                Character.owner_user_id == Seat.user_id,
                Character.status != "premade",
            )
            .order_by(Character.created_at)
        )
    ).all()
    return [
        hero
        for hero in rows
        if (hero.sheet or {}).get("rules_version") == "universal.v1" and "source_library_id" not in hero.sheet
    ]


async def backfill(session, apply: bool) -> int:
    count = 0
    for hero in await candidates(session):
        try:
            sheet = base_sheet(hero.sheet)
        except ValueError as e:
            print(f"пропуск {hero.id} «{hero.name}»: лист не читается ({e.__class__.__name__})")
            continue
        portrait = await session.get(HeroPortrait, hero.portrait_id) if hero.portrait_id else None
        own_portrait = portrait is not None and portrait.owner_user_id == hero.owner_user_id
        print(
            f"{hero.id} «{hero.name}» ({hero.status}, ур. {hero.sheet.get('level')}) → библиотека "
            f"{hero.owner_user_id}{', с портретом' if own_portrait else ''}"
        )
        count += 1
        if apply:
            library = LibraryCharacter(
                id=new_id("lc"),
                owner_user_id=hero.owner_user_id,
                name=hero.name,
                portrait_id=hero.portrait_id if own_portrait else None,
                sheet=sheet.model_dump(mode="json"),
            )
            session.add(library)
            hero.sheet = {**hero.sheet, "source_library_id": library.id}
    if apply:
        await session.commit()
    return count


async def main(apply: bool) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import Settings

    engine = create_async_engine(Settings.from_env().database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        count = await backfill(session, apply)
    await engine.dispose()
    print(f"{'Перенесено' if apply else 'Будет перенесено'}: {count}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="записать изменения в базу")
    asyncio.run(main(parser.parse_args().apply))
