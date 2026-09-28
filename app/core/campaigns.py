"""Кампании, места и приглашения: правила доступа из ТЗ, раздел 2, и состав из раздела 5.2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentConfig,
    Campaign,
    CampaignSecret,
    ContentPack,
    Invite,
    ModelProfile,
    Seat,
    User,
    as_utc,
    now,
)

MAX_PLAYERS = 6
DIFFICULTIES = ("easy", "normal", "hard", "deadly")
PROVIDERS = ("claude", "gemini", "local")
DEFAULT_PARTY = {"min": 3, "recommended": 4, "max": 6}  # бюджет встреч SRD рассчитан на отряд из 4
DEFAULT_SETTINGS = {
    "turn_timeout_sec": 300,  # ход до 5 минут, игра вживую
    "collect_window_sec": 60,  # окно сбора реплик в свободном режиме
    "spend_limit_usd": None,  # лимит расходов задаёт Admin, по умолчанию нет
}


class AccessDenied(Exception):
    pass


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


@dataclass(frozen=True)
class Viewer:
    """Кто смотрит на кампанию: владелец и/или занятое им место."""

    user: User
    campaign: Campaign
    seat: Seat | None

    @property
    def is_owner(self) -> bool:
        return self.campaign.owner_id == self.user.id

    @property
    def is_master(self) -> bool:
        return self.seat is not None and self.seat.role == "master"

    @property
    def is_player(self) -> bool:
        return self.seat is not None and self.seat.role == "player"

    @property
    def can_manage_members(self) -> bool:
        return self.is_owner

    @property
    def can_control_session(self) -> bool:
        return self.is_owner or self.is_master


def is_admin(user: User) -> bool:
    return user.platform_role in ("admin", "super_admin")


def party_size(pack: ContentPack | None, difficulty: str) -> dict:
    """Рекомендация размера отряда: из pack.yaml (party_size), со сдвигом по сложности, если пакет его задаёт
    (difficulty_levels: [{id, party_size_delta}]). Без пакета — 4 из 3–6 по SRD."""
    manifest = pack.manifest if pack is not None else {}
    base = {**DEFAULT_PARTY, **(manifest.get("party_size") or {})}
    delta = 0
    for level in manifest.get("difficulty_levels") or []:
        if isinstance(level, dict) and level.get("id") == difficulty:
            delta = int(level.get("party_size_delta", 0))
    rec = min(max(base["recommended"] + delta, base["min"]), min(base["max"], MAX_PLAYERS))
    return {"min": base["min"], "recommended": rec, "max": min(base["max"], MAX_PLAYERS)}


def seat_for(campaign: Campaign, user_id: str) -> Seat | None:
    return next((s for s in campaign.seats if s.occupant_type == "human" and s.user_id == user_id), None)


def master_seat(campaign: Campaign) -> Seat:
    return next(s for s in campaign.seats if s.role == "master")


async def get_viewer(session: AsyncSession, user: User, campaign_id: str) -> Viewer:
    """Доступ к кампании есть у владельца и у тех, кто занимает в ней место. Остальным — «не найдено»."""
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise NotFound("кампания не найдена")
    viewer = Viewer(user, campaign, seat_for(campaign, user.id))
    if not viewer.is_owner and viewer.seat is None:
        raise NotFound("кампания не найдена")
    return viewer


async def list_campaigns(session: AsyncSession, user: User) -> list[Campaign]:
    seated = select(Seat.campaign_id).where(Seat.user_id == user.id, Seat.occupant_type == "human")
    q = select(Campaign).where((Campaign.owner_id == user.id) | Campaign.id.in_(seated))
    return list((await session.scalars(q.order_by(Campaign.created_at.desc()))).all())


async def default_model_profile(session: AsyncSession) -> ModelProfile | None:
    return (await session.scalars(select(ModelProfile).where(ModelProfile.is_default.is_(True)))).first()


def apply_model(agent: AgentConfig, provider: str, model: str, temperature: float, api_base: str | None, profile_id):
    agent.provider, agent.model, agent.temperature = provider, model, temperature
    agent.settings = {
        **(agent.settings or {}),
        "api_base": api_base if provider == "local" else None,
        "model_profile_id": profile_id,
    }


async def agent_for_master(session: AsyncSession, master: dict, agent: AgentConfig | None = None) -> AgentConfig:
    """Настройки ИИ-мастера: профиль модели из админки, явные провайдер и модель или профиль по умолчанию.
    Кампания хранит копию: правка профиля потом не меняет идущие кампании без явной смены модели."""
    agent = agent or AgentConfig(settings={})
    temperature = master.get("temperature")
    profile_id = master.get("model_profile_id")
    profile = None
    if profile_id:
        profile = await session.get(ModelProfile, profile_id)
        if profile is None:
            raise NotFound("профиль модели не найден")
    elif not master.get("provider"):
        profile = await default_model_profile(session)
    if profile is not None:
        t = profile.temperature if temperature is None else float(temperature)
        apply_model(agent, profile.provider, profile.model, t, profile.api_base, profile.id)
    else:
        provider = master.get("provider") or "claude"
        if provider not in PROVIDERS:
            raise Conflict(f"провайдер один из: {', '.join(PROVIDERS)}")
        if provider != "claude" and not master.get("model"):
            raise Conflict("для этого провайдера укажите модель: имя модели, как оно записано у провайдера")
        t = (agent.temperature if agent.temperature is not None else 0.8) if temperature is None else float(temperature)
        apply_model(agent, provider, str(master.get("model") or ""), t, master.get("api_base"), None)
    if "style" in master:
        agent.persona = master.get("style")
    return agent


async def create_campaign(
    session: AsyncSession,
    owner: User,
    *,
    name: str,
    ruleset_version: str,
    pack: ContentPack | None,
    difficulty: str,
    players: int | None,
    master: dict,
    public_intro: str = "",
    settings: dict | None = None,
    owner_plays: bool = True,
) -> Campaign:
    if not is_admin(owner):
        raise AccessDenied("кампании создаёт только Admin")
    if difficulty not in DIFFICULTIES:
        raise Conflict(f"сложность одна из: {', '.join(DIFFICULTIES)}")
    rec = party_size(pack, difficulty)
    count = players if players is not None else rec["recommended"]
    if not 1 <= count <= MAX_PLAYERS:
        raise Conflict(f"игроков от 1 до {MAX_PLAYERS}")

    master_type = master.get("type")
    if master_type == "owner":
        m = Seat(role="master", position=0, occupant_type="human", user_id=owner.id, joined_at=now())
    elif master_type == "agent":
        agent = await agent_for_master(session, master)
        session.add(agent)
        await session.flush()
        m = Seat(role="master", position=0, occupant_type="agent", agent_config_id=agent.id, joined_at=now())
    else:
        raise Conflict("мастер: {type: owner} или {type: agent, provider, model}")

    campaign = Campaign(
        owner_id=owner.id,
        name=name,
        ruleset_id="dnd5e",
        ruleset_version=ruleset_version,
        pack_id=pack.id if pack else None,
        pack_version=pack.version if pack else None,
        public_intro=public_intro,
        difficulty=difficulty,
        party_size_recommended=rec["recommended"],
        settings={**DEFAULT_SETTINGS, **(settings or {})},
        seats=[m, *(Seat(role="player", position=i) for i in range(1, count + 1))],
    )
    if master_type != "owner" and owner_plays:
        # владелец, который не ведёт игру сам, сразу садится на первое место игрока
        first = campaign.seats[1]
        first.occupant_type, first.user_id, first.joined_at = "human", owner.id, now()
    session.add(campaign)
    await session.flush()
    session.add(CampaignSecret(campaign_id=campaign.id))
    await session.flush()
    return campaign


async def create_invite(
    session: AsyncSession, viewer: Viewer, *, expires_at: datetime | None, max_uses: int | None
) -> Invite:
    if not viewer.can_manage_members:
        raise AccessDenied("приглашать может только владелец")
    invite = Invite(campaign_id=viewer.campaign.id, created_by=viewer.user.id, expires_at=expires_at, max_uses=max_uses)
    session.add(invite)
    await session.flush()
    return invite


def invite_problem(invite: Invite | None) -> str | None:
    if invite is None or invite.revoked:
        return "приглашение недействительно"
    exp = as_utc(invite.expires_at)
    if exp is not None and exp <= datetime.now(UTC):
        return "срок приглашения истёк"
    if invite.max_uses is not None and invite.uses >= invite.max_uses:
        return "приглашение уже использовано"
    return None


async def accept_invite(session: AsyncSession, user: User, token: str) -> Seat:
    """Сажает пользователя на первое свободное место игрока."""
    invite = await session.get(Invite, token, with_for_update=True)
    problem = invite_problem(invite)
    if problem:
        raise Conflict(problem)
    campaign = await session.get(Campaign, invite.campaign_id)
    if campaign.status == "ended":
        raise Conflict("кампания завершена")
    existing = seat_for(campaign, user.id)
    if existing is not None:
        if existing.role == "master":
            raise Conflict("мастер не занимает место игрока")
        return existing
    free = next((s for s in campaign.seats if s.role == "player" and s.occupant_type == "empty"), None)
    if free is None:
        raise Conflict("свободных мест нет")
    free.occupant_type, free.user_id, free.joined_at = "human", user.id, now()
    invite.uses += 1
    await session.flush()
    return free


async def take_seat(session: AsyncSession, viewer: Viewer) -> Seat:
    """Владелец садится на свободное место игрока в своей кампании (без приглашения)."""
    if not viewer.is_owner:
        raise AccessDenied("занять место без приглашения может только владелец")
    if viewer.seat is not None:
        raise Conflict("вы уже на месте " + ("мастера" if viewer.is_master else "игрока"))
    free = next((s for s in viewer.campaign.seats if s.role == "player" and s.occupant_type == "empty"), None)
    if free is None:
        raise Conflict("свободных мест нет")
    free.occupant_type, free.user_id, free.joined_at = "human", viewer.user.id, now()
    await session.flush()
    return free


async def free_seat(session: AsyncSession, viewer: Viewer, seat_id: str) -> Seat:
    """Исключение игрока: место освобождается, персонаж остаётся за местом (этап 3)."""
    if not viewer.can_manage_members:
        raise AccessDenied("исключать может только владелец")
    seat = next((s for s in viewer.campaign.seats if s.id == seat_id), None)
    if seat is None:
        raise NotFound("место не найдено")
    if seat.role == "master":
        raise Conflict("место мастера так не освобождается")
    seat.occupant_type, seat.user_id, seat.agent_config_id, seat.joined_at = "empty", None, None, None
    await session.flush()
    return seat


async def leave_campaign(session: AsyncSession, viewer: Viewer) -> None:
    if viewer.seat is None or viewer.seat.role != "player":
        raise Conflict("покинуть кампанию может только игрок")
    s = viewer.seat
    s.occupant_type, s.user_id, s.joined_at = "empty", None, None
    await session.flush()
