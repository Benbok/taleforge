"""Короткие транзакции изменения мира (спецификация генерации сцен, §6.2; docs/world-objects-delivery2.md).

``Campaign.world_revision`` — версия мира кампании. Защищённая запись начинается с условного
``UPDATE campaigns SET world_revision = world_revision + 1 WHERE id = … AND world_revision = expected``:
ноль строк — ``WorldConflict`` и откат всей транзакции, повторить можно только после повторной проверки
предусловий. Guard берётся один раз на транзакцию; вызванные из неё helpers пользуются тем же guard.

Участвуют все писатели, а не только инструменты: обработчик ``before_flush`` берёт guard кампании перед
любой вставкой, изменением или удалением защищённой строки. Ожидаемая ревизия — та, что прочитана при
загрузке мира (``load_world`` → ``remember_base``); без загруженного мира запись увеличивает ревизию без
условия, это точка сериализации короткого запроса. Сообщения, события, ходы и учёт вызовов модели мир не
меняют и guard не берут.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key

from app.core.campaigns import Conflict
from app.db.models import (
    ActiveEffect,
    Campaign,
    CampaignSecret,
    Character,
    Entity,
    InventoryItem,
    Knowledge,
    KnownFact,
    MapMemory,
    NarrativeFact,
    NarrativeState,
    NarrativeThread,
    PlotAnchorBinding,
    Scene,
    Seat,
    WorldGenerationState,
)

GUARD = "world_guard"  # session.info: {campaign_id: (транзакция, где взят guard, новая ревизия)}
BASE = "world_base"  # session.info: {campaign_id: ревизия, прочитанная вместе с миром}

# строки с campaign_id, изменение которых меняет мир: состояние, видимость, права и источники
_BY_CAMPAIGN = (
    Character,
    Entity,
    ActiveEffect,
    KnownFact,
    NarrativeFact,
    NarrativeState,
    NarrativeThread,
    Scene,
    CampaignSecret,
    WorldGenerationState,
    PlotAnchorBinding,
    Seat,
)
_BY_CHARACTER = (InventoryItem, Knowledge, MapMemory)
# поля кампании, которые меняют разрешённый контент и правила; last_seq и updated_at — нет
CAMPAIGN_FIELDS = (
    "settings",
    "content_chain",
    "pack_id",
    "pack_version",
    "ruleset_id",
    "ruleset_version",
    "difficulty",
)


class WorldConflict(Conflict):
    """Мир кампании изменился после чтения: запись откатывается целиком."""

    def __init__(self, campaign_id: str, expected: int | None):
        super().__init__("мир изменился, пока шло действие: обновите сцену и повторите")
        self.campaign_id = campaign_id
        self.expected = expected


def _innermost(session: Session):
    return session.get_nested_transaction() or session.get_transaction()


def _acquire(session: Session, campaign_id: str, expected: int | None) -> int | None:
    guards: dict[str, tuple[Any, int]] = session.info.setdefault(GUARD, {})
    if campaign_id in guards:
        return guards[campaign_id][1]
    conn = session.connection()
    table = Campaign.__table__
    stmt = update(table).where(table.c.id == campaign_id)
    if expected is not None:
        stmt = stmt.where(table.c.world_revision == expected)
    stmt = stmt.values(world_revision=table.c.world_revision + 1).returning(table.c.world_revision)
    revision = conn.execute(stmt).scalar()
    if revision is None:
        if expected is None:
            return None  # кампании нет (удаляется): защищать нечего
        raise WorldConflict(campaign_id, expected)
    guards[campaign_id] = (_innermost(session), revision)
    held = session.identity_map.get(identity_key(Campaign, campaign_id))
    if held is not None:
        set_committed_value(held, "world_revision", revision)
    return revision


async def world_write(session: AsyncSession, campaign_id: str, expected_revision: int | None = None) -> int | None:
    """Начать защищённую запись мира кампании. Повтор в той же транзакции возвращает уже взятую ревизию.

    ``expected_revision`` — ревизия, от которой посчитано изменение; None — взять ревизию, прочитанную с миром
    (``remember_base``), а без неё — увеличить без условия."""
    expected = expected_revision if expected_revision is not None else base_revision(session, campaign_id)
    return await session.run_sync(_acquire, campaign_id, expected)


def remember_base(session: AsyncSession | Session, campaign_id: str, revision: int, *, fresh: bool = False) -> None:
    """Ревизия, от которой эта транзакция читает мир. Первое чтение остаётся мерой, пока транзакция не кончится:
    объекты из него уже лежат в сессии. ``fresh`` — мир перечитан целиком (populate_existing)."""
    sync = session.sync_session if isinstance(session, AsyncSession) else session
    if campaign_id in sync.info.get(GUARD, {}):
        return
    bases = sync.info.setdefault(BASE, {})
    if fresh:
        bases[campaign_id] = revision
    else:
        bases.setdefault(campaign_id, revision)


def base_revision(session: AsyncSession | Session, campaign_id: str) -> int | None:
    sync = session.sync_session if isinstance(session, AsyncSession) else session
    return sync.info.get(BASE, {}).get(campaign_id)


def held(session: AsyncSession | Session, campaign_id: str) -> bool:
    sync = session.sync_session if isinstance(session, AsyncSession) else session
    return campaign_id in sync.info.get(GUARD, {})


async def read_revision(session: AsyncSession, campaign_id: str) -> int:
    return int(await session.scalar(select(Campaign.world_revision).where(Campaign.id == campaign_id)) or 0)


# --- автоматическое участие всех писателей ---


def _character_campaign(session: Session, character_id: str | None) -> str | None:
    if not character_id:
        return None
    obj = session.identity_map.get(identity_key(Character, character_id))
    if obj is None:
        obj = next((o for o in session.new if isinstance(o, Character) and o.id == character_id), None)
    if obj is not None:
        return obj.campaign_id
    q = select(Character.campaign_id).where(Character.id == character_id)
    return session.connection().execute(q).scalar()


def _campaign_changed(obj: Campaign) -> bool:
    state = sa_inspect(obj)
    return any(state.attrs[name].history.has_changes() for name in CAMPAIGN_FIELDS)


def _touched(session: Session) -> set[str]:
    out: set[str] = set()
    skip = {o.id for o in session.new if isinstance(o, Campaign)}
    skip |= {o.id for o in session.deleted if isinstance(o, Campaign)}
    dirty = [o for o in session.dirty if session.is_modified(o, include_collections=False)]
    for obj in [*session.new, *dirty, *session.deleted]:
        cid: str | None = None
        if isinstance(obj, Campaign):
            if obj in session.dirty and _campaign_changed(obj):
                cid = obj.id
        elif isinstance(obj, _BY_CAMPAIGN):
            cid = obj.campaign_id
        elif isinstance(obj, _BY_CHARACTER):
            cid = _character_campaign(session, obj.character_id)
        if cid and cid not in skip:
            out.add(cid)
    return out


@event.listens_for(Session, "before_flush")
def _guard_writes(session: Session, _flush_context, _instances) -> None:
    for cid in sorted(_touched(session)):
        _acquire(session, cid, session.info.get(BASE, {}).get(cid))


@event.listens_for(Session, "after_soft_rollback")
def _release_on_rollback(session: Session, previous_transaction) -> None:
    """Откат точки сохранения, где взят guard, откатил и его UPDATE: следующая запись возьмёт guard заново."""
    if previous_transaction.parent is None:
        session.info.pop(GUARD, None)
        session.info.pop(BASE, None)
        return
    guards = session.info.get(GUARD) or {}
    for cid, (tx, _rev) in list(guards.items()):
        t = tx
        while t is not None:
            if t is previous_transaction:
                del guards[cid]
                break
            t = t.parent


@event.listens_for(Session, "after_transaction_end")
def _release_on_end(session: Session, transaction) -> None:
    if transaction.parent is None:
        session.info.pop(GUARD, None)
        session.info.pop(BASE, None)
