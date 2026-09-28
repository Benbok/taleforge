"""Главная страница нового клиента: карточки «Мои кампании» и тема пакета (документ «Дизайн фронтенда»).

Карточка несёт только то, что участник и так видит в кампании: статус, свою роль и героя, публичный состав отряда
с онлайном и первую строку пересказа для игроков. Тайн, каркаса и анкеты здесь нет.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.agents import memory
from app.api.deps import SessionDep, UserDep
from app.content import theme as themes
from app.core import campaigns as svc
from app.core.inspect import types_for
from app.db.models import Campaign, Character, ContentPack, GameSession

router = APIRouter(prefix="/api", tags=["home"])

LIVE_HEROES = ("approved", "active")


class PartyMember(BaseModel):
    seat_id: str
    role: str
    occupant_type: str
    user_name: str | None = None
    hero_name: str | None = None
    online: bool = False


class CampaignCard(BaseModel):
    id: str
    name: str
    world: str | None = None
    status: str  # lobby | active | paused | ended
    session_live: bool
    waiting_players: int
    my_role: str | None = None
    is_owner: bool
    hero: dict[str, Any] | None = None
    party: list[PartyMember]
    recap: str | None = None
    last_session_at: datetime | None = None
    created_at: datetime


def _first_line(text: str | None) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    line = text.split("\n", 1)[0]
    return line if len(line) <= 240 else line[:239].rstrip() + "…"


@router.get("/theme")
async def default_theme() -> dict:
    """Базовая тема без пакета: для страницы входа и списка кампаний."""
    return themes.merge([])


@router.get("/campaigns/{campaign_id}/theme")
async def campaign_theme(campaign_id: str, user: UserDep, session: SessionDep) -> dict:
    """Тема кампании: базовая, поверх неё — темы пакетов цепочки по порядку (база правил, потом мир)."""
    v = await svc.get_viewer(session, user, campaign_id)
    layers = []
    for pid, ver in v.campaign.content_chain or []:
        pack = await session.get(ContentPack, (pid, ver))
        if pack and (pack.manifest or {}).get("theme"):
            layers.append(pack.manifest["theme"])
    return themes.merge(layers)


@router.get("/campaigns/{campaign_id}/entity-types")
async def entity_types(campaign_id: str, ids: str, user: UserDep, session: SessionDep) -> dict[str, str]:
    """Типы сущностей из разметки ``[[id|текст]]`` — чтобы подчеркнуть слово цветом типа до клика."""
    v = await svc.get_viewer(session, user, campaign_id)
    return await types_for(session, v, ids.split(","))


@router.get("/me/campaigns")
async def my_campaigns(user: UserDep, session: SessionDep, request: Request) -> list[CampaignCard]:
    hub = request.app.state.hub
    out = []
    for c in await svc.list_campaigns(session, user):
        out.append(await _card(session, c, user, hub.online_users(c.id)))
    return out


async def _card(session, c: Campaign, user, online: set[str]) -> CampaignCard:
    heroes = (
        await session.scalars(select(Character).where(Character.campaign_id == c.id, Character.seat_id.is_not(None)))
    ).all()
    by_seat: dict[str, Character] = {}
    for ch in heroes:
        # у места может быть несколько героев (погибший и новый): в карточке — живой, иначе последний
        cur = by_seat.get(ch.seat_id)
        if cur is None or (ch.status in LIVE_HEROES and cur.status not in LIVE_HEROES):
            by_seat[ch.seat_id] = ch
    mine = svc.seat_for(c, user.id)
    hero = by_seat.get(mine.id) if mine else None
    game = await session.scalar(
        select(GameSession).where(GameSession.campaign_id == c.id).order_by(GameSession.started_at.desc()).limit(1)
    )
    last = await memory.latest(session, c.id)
    world = None
    if c.pack_id:
        world = await session.scalar(
            select(ContentPack.name).where(ContentPack.id == c.pack_id, ContentPack.version == c.pack_version)
        )
    party = [
        PartyMember(
            seat_id=s.id,
            role=s.role,
            occupant_type=s.occupant_type,
            user_name=s.user.name if s.user else None,
            hero_name=by_seat[s.id].name if s.id in by_seat and s.role == "player" else None,
            online=bool(s.user_id and s.user_id in online),
        )
        for s in sorted(c.seats, key=lambda s: (s.role != "master", s.position))
    ]
    return CampaignCard(
        id=c.id,
        name=c.name,
        world=world,
        status=c.status,
        session_live=bool(game and game.ended_at is None),
        waiting_players=sum(1 for s in c.seats if s.role == "player" and s.occupant_type == "empty"),
        my_role=mine.role if mine else None,
        is_owner=c.owner_id == user.id,
        hero={"id": hero.id, "name": hero.name, "status": hero.status, "level": (hero.sheet or {}).get("level")}
        if hero
        else None,
        party=party,
        recap=_first_line((last.content or {}).get("recap")) if last else None,
        last_session_at=(game.ended_at or game.started_at) if game else None,
        created_at=c.created_at,
    )
