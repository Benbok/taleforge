"""Universal character ownership, public projections and admission safety."""

from __future__ import annotations

import copy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import bonds
from app.core.campaigns import AccessDenied, Conflict, NotFound, Viewer
from app.core.world import get_scene
from app.db.models import Campaign, CampaignSecret, Character, Event, MasterTurn, as_utc

ACTIVE = ("draft", "submitted", "approved", "active")
ADMISSION_CONFLICT = "Нельзя менять состав героев во время активной сессии или игрового хода."


def _own(viewer: Viewer, ch: Character) -> None:
    if ch.owner_user_id != viewer.user.id or viewer.seat is None or ch.seat_id != viewer.seat.id:
        raise AccessDenied("это не ваш персонаж")


async def get_character(session: AsyncSession, viewer: Viewer, character_id: str) -> Character:
    ch = await session.get(Character, character_id)
    if ch is None or ch.campaign_id != viewer.campaign.id:
        raise NotFound("персонаж не найден")
    return ch


async def ensure_character_admission_allowed(session: AsyncSession, campaign: Campaign) -> None:
    c = await session.get(Campaign, campaign.id, with_for_update=True)
    if c is None or c.status == "ended":
        raise Conflict(ADMISSION_CONFLICT)

    from app.core import chat

    active = await chat.active_session(session, campaign.id)
    if active is not None or c.status == "active":
        raise Conflict(ADMISSION_CONFLICT)

    scene = await get_scene(session, campaign.id)
    if scene is not None:
        if scene.mode == "combat" or bool(scene.turn_order):
            raise Conflict(ADMISSION_CONFLICT)
        st = scene.state or {}
        if bool(st.get("combats")) or bool(st.get("combat")):
            raise Conflict(ADMISSION_CONFLICT)

    running_turn = (
        await session.scalars(
            select(MasterTurn).where(
                MasterTurn.campaign_id == campaign.id,
                MasterTurn.status == "running",
            )
        )
    ).first()
    if running_turn is not None:
        raise Conflict(ADMISSION_CONFLICT)


async def record_secret_link(
    session: AsyncSession, campaign_id: str, ch: Character, text: str, *, ref: str | None = None
) -> None:
    """Тайная связь истории героя с сюжетом: в скрытые данные кампании, игрок её не видит. С ``ref`` она
    становится личным крючком — привязкой к узлу, NPC, злодею или месту каркаса."""
    from app.core import plot as plots

    secret = await session.get(CampaignSecret, campaign_id)
    if secret is None:
        secret = CampaignSecret(campaign_id=campaign_id)
        session.add(secret)
    plot = copy.deepcopy(secret.plot or {})
    plot.setdefault("character_links", {})[ch.id] = text
    if ref:
        try:
            plots.set_hook(plot, ch.id, ch.name, ref, text)
        except plots.PlotError as e:
            raise Conflict(str(e)) from e
    secret.plot = plot
    await session.flush()


async def review_failure(session: AsyncSession, ch: Character) -> str | None:
    """Почему ИИ-мастер не проверил героя, если последняя попытка после отправки сорвалась."""
    return (await review_state(session, ch)).get("review_error")


async def review_state(session: AsyncSession, ch: Character) -> dict:
    """Recover the latest submission's attempt without restarting a paid task."""
    if ch.status != "submitted":
        return {}
    ev = (
        await session.scalars(
            select(Event)
            .where(
                Event.campaign_id == ch.campaign_id,
                Event.target_id == ch.id,
                Event.tool.in_(["review_failed", "review_started", "review_finished"]),
            )
            .order_by(Event.created_at.desc())
            .limit(1)
        )
    ).first()
    if ev is None or (ch.updated_at and as_utc(ev.created_at) < as_utc(ch.updated_at)):
        return {"review_status": "queued", "review_error": None, "review_attempt_id": None}
    data = ev.payload or {}
    attempt = data.get("attempt_id")
    if ev.tool == "review_failed":
        return {
            "review_status": "failed",
            "review_error": data.get("error") or "неизвестная ошибка",
            "review_attempt_id": attempt,
        }
    running = session.info.get("review_running", {}).get((ch.campaign_id, ch.id))
    if (
        ev.tool == "review_started"
        and data.get("process_id") == session.info.get("review_process_id")
        and attempt is not None
        and running == attempt
    ):
        return {"review_status": "running", "review_error": None, "review_attempt_id": attempt}
    return {
        "review_status": "interrupted",
        "review_error": "Проверка прервана. Повторите её или обратитесь к мастеру.",
        "review_attempt_id": attempt,
    }


def public_view(ch: Character, entities=()) -> dict:
    from app.core.companions import companion_is_active, companion_record, public_companion
    from app.core.universal.portraits import portrait_url

    res = ch.resources or {}
    return {
        "id": ch.id,
        "name": ch.name,
        "portrait_url": portrait_url(ch.portrait_id),
        "seat_id": ch.seat_id,
        "status": ch.status,
        "public_bio": ch.public_bio,
        "level": (ch.sheet or {}).get("level", 1),
        "hp": res.get("hp"),
        "hp_max": res.get("hp_max"),
        "dead": bool(res.get("dead")),
        # спасброски от смерти бросаются открыто, как за столом: трекер видят все
        "bonds": bonds.public_bonds(ch),
        "companions": [
            public_companion(entity)
            for entity in entities
            if companion_record(entity) and companion_record(entity).get("of") == ch.id and companion_is_active(entity)
        ],
    }


def full_view(ch, cat=None, inventory=(), effects=(), entities=()):
    from app.core.universal.state import game_card_of

    if (ch.sheet or {}).get("rules_version") != "universal.v1":
        raise Conflict("Поддерживается только универсальная карточка героя.")
    return game_card_of(ch)
