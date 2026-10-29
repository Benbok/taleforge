"""Иллюстрации и портреты делаются внутри процесса: перезапуск обрывает задачу, а запись осталась бы «pending»
до конца аренды, и игрок всё это время видел бы «Создаётся иллюстрация…». При старте такие записи закрываются."""

from sqlalchemy import update

from app.db.models import Artwork, EquipmentArtwork, LocationArtwork, NpcPortrait


async def fail_interrupted_artwork(maker) -> int:
    """Записи в работе при старте принадлежали умершему процессу: они помечаются неудавшимися и их можно повторить."""
    total = 0
    async with maker() as session:
        for model in (LocationArtwork, EquipmentArtwork, NpcPortrait, Artwork):
            result = await session.execute(
                update(model).where(model.status == "pending").values(status="failed", error="restart")
            )
            total += result.rowcount or 0
        await session.commit()
    return total
