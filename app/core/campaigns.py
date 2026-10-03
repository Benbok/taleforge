"""РљР°РјРїР°РЅРёРё, РјРµСЃС‚Р° Рё РїСЂРёРіР»Р°С€РµРЅРёСЏ: РїСЂР°РІРёР»Р° РґРѕСЃС‚СѓРїР° РёР· РўР—, СЂР°Р·РґРµР» 2, Рё СЃРѕСЃС‚Р°РІ РёР· СЂР°Р·РґРµР»Р° 5.2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import persona, personas
from app.db.models import (
    AgentConfig,
    Campaign,
    CampaignSecret,
    ContentPack,
    Invite,
    MasterPersona,
    MasterPreset,
    ModelProfile,
    Seat,
    User,
    as_utc,
    now,
)

MAX_PLAYERS = 6
DIFFICULTIES = ("easy", "normal", "hard", "deadly")
PROVIDERS = ("claude", "gemini", "local")
DEFAULT_PARTY = {"min": 3, "recommended": 4, "max": 6}  # Р±СЋРґР¶РµС‚ РІСЃС‚СЂРµС‡ SRD СЂР°СЃСЃС‡РёС‚Р°РЅ РЅР° РѕС‚СЂСЏРґ РёР· 4
DEFAULT_SETTINGS = {
    "turn_timeout_sec": 300,  # С…РѕРґ РґРѕ 5 РјРёРЅСѓС‚, РёРіСЂР° РІР¶РёРІСѓСЋ
    "collect_window_sec": 60,  # РѕРєРЅРѕ СЃР±РѕСЂР° СЂРµРїР»РёРє РІ СЃРІРѕР±РѕРґРЅРѕРј СЂРµР¶РёРјРµ
    "spend_limit_usd": None,  # Р»РёРјРёС‚ СЂР°СЃС…РѕРґРѕРІ Р·Р°РґР°С‘С‚ Admin, РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ РЅРµС‚
    "tts_provider": "gemini",
    "tts_enabled": True,  # РѕР·РІСѓС‡РєР° СЂРµРїР»РёРє РјР°СЃС‚РµСЂР° РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ РІРєР»СЋС‡РµРЅР°
    "tts_voice": "Fenrir",  # РіРѕР»РѕСЃ РѕР·РІСѓС‡РєРё РјР°СЃС‚РµСЂР° РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ (Fenrir, Puck, Charon, Kore, Aoede)
}


class AccessDenied(Exception):
    pass


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


@dataclass(frozen=True)
class Viewer:
    """РљС‚Рѕ СЃРјРѕС‚СЂРёС‚ РЅР° РєР°РјРїР°РЅРёСЋ: РІР»Р°РґРµР»РµС† Рё/РёР»Рё Р·Р°РЅСЏС‚РѕРµ РёРј РјРµСЃС‚Рѕ."""

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
    def can_review(self) -> bool:
        """Р“РµСЂРѕРµРІ РїСЂРѕРІРµСЂСЏРµС‚ РјР°СЃС‚РµСЂ. Р•СЃР»Рё РјР°СЃС‚РµСЂ вЂ” РР, РІР»Р°РґРµР»РµС† С‚РѕР¶Рµ РјРѕР¶РµС‚ РїСЂРѕРІРµСЂРёС‚СЊ РІСЂСѓС‡РЅСѓСЋ: РІРґСЂСѓРі РјРѕРґРµР»СЊ
        РЅРµРґРѕСЃС‚СѓРїРЅР° РёР»Рё РЅРµ СЃРїСЂР°РІРёР»Р°СЃСЊ."""
        return self.is_master or (self.is_owner and master_seat(self.campaign).occupant_type == "agent")

    @property
    def can_manage_members(self) -> bool:
        return self.is_owner

    @property
    def can_control_session(self) -> bool:
        return self.is_owner or self.is_master


def is_admin(user: User) -> bool:
    return user.platform_role in ("admin", "super_admin")


def party_size(pack: ContentPack | None, difficulty: str) -> dict:
    """Р РµРєРѕРјРµРЅРґР°С†РёСЏ СЂР°Р·РјРµСЂР° РѕС‚СЂСЏРґР°: РёР· pack.yaml (party_size), СЃРѕ СЃРґРІРёРіРѕРј РїРѕ СЃР»РѕР¶РЅРѕСЃС‚Рё, РµСЃР»Рё РїР°РєРµС‚ РµРіРѕ Р·Р°РґР°С‘С‚
    (difficulty_levels: [{id, party_size_delta}]). Р‘РµР· РїР°РєРµС‚Р° вЂ” 4 РёР· 3вЂ“6 РїРѕ SRD."""
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


async def get_viewer(
    session: AsyncSession, user: User, campaign_id: str, as_seat: str | None = None, *, ai_seat: bool = False
) -> Viewer:
    """Р”РѕСЃС‚СѓРї Рє РєР°РјРїР°РЅРёРё РµСЃС‚СЊ Сѓ РІР»Р°РґРµР»СЊС†Р° Рё Сѓ С‚РµС…, РєС‚Рѕ Р·Р°РЅРёРјР°РµС‚ РІ РЅРµР№ РјРµСЃС‚Рѕ. РћСЃС‚Р°Р»СЊРЅС‹Рј вЂ” В«РЅРµ РЅР°Р№РґРµРЅРѕВ».

    ``as_seat`` вЂ” РјРµСЃС‚Рѕ, С‡СЊРµРіРѕ РіРµСЂРѕСЏ СЌС‚РѕС‚ РёРіСЂРѕРє РІРµРґС‘С‚ РїРѕ РёС‚РѕРіР°Рј РіРѕР»РѕСЃРѕРІР°РЅРёСЏ, РїРѕРєР° РµРіРѕ РёРіСЂРѕРє РѕС„Р»Р°Р№РЅ (СЂР°Р·РґРµР» 11).
    ``ai_seat`` вЂ” РµС‰С‘ Рё РјРµСЃС‚Рѕ РР-РёРіСЂРѕРєР°, Р·Р° РєРѕС‚РѕСЂРѕРµ РІР»Р°РґРµР»РµС† СЃРѕР±РёСЂР°РµС‚ РіРµСЂРѕСЏ (СЌС‚Р°Рї 9); РіРѕРІРѕСЂРёС‚ Р·Р° РЅРµРіРѕ С‚РѕР»СЊРєРѕ РР."""
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise NotFound("РєР°РјРїР°РЅРёСЏ РЅРµ РЅР°Р№РґРµРЅР°")
    viewer = Viewer(user, campaign, seat_for(campaign, user.id))
    if not viewer.is_owner and viewer.seat is None:
        raise NotFound("РєР°РјРїР°РЅРёСЏ РЅРµ РЅР°Р№РґРµРЅР°")
    if as_seat:
        seat = next((s for s in campaign.seats if s.id == as_seat), None)
        # РІР»Р°РґРµР»РµС† СЃРѕР±РёСЂР°РµС‚ РіРµСЂРѕСЏ РР-РёРіСЂРѕРєСѓ Р·Р° РµРіРѕ РјРµСЃС‚Рѕ (СЌС‚Р°Рї 9)
        builds = ai_seat and seat is not None and seat.occupant_type == "agent" and not seat.delegated_from
        if (
            seat is None
            or seat.role != "player"
            or not (seat.stand_in_user_id == user.id or builds and viewer.is_owner)
        ):
            raise NotFound("РІС‹ РЅРµ РІРµРґС‘С‚Рµ СЌС‚РѕРіРѕ РіРµСЂРѕСЏ: РµРіРѕ РёРіСЂРѕРє РІРµСЂРЅСѓР»СЃСЏ РёР»Рё РіРѕР»РѕСЃРѕРІР°РЅРёРµ СЂРµС€РёР»Рѕ РёРЅР°С‡Рµ")
        return Viewer(user, campaign, seat)
    return viewer


def stand_in_seats(campaign: Campaign, user_id: str) -> list[str]:
    """РњРµСЃС‚Р°, С‡СЊРёС… РіРµСЂРѕРµРІ СЌС‚РѕС‚ РёРіСЂРѕРє СЃРµР№С‡Р°СЃ РІРµРґС‘С‚ Р·Р° РѕС‚СЃСѓС‚СЃС‚РІСѓСЋС‰РёС…."""
    return [s.id for s in campaign.seats if s.stand_in_user_id == user_id]


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


async def apply_persona(session: AsyncSession, owner: User, agent: AgentConfig, choice: dict) -> None:
    """РџРµСЂСЃРѕРЅР° РјР°СЃС‚РµСЂР°: СЃРІРѕСЏ РёР· РїСЂРѕС„РёР»СЏ РІР»Р°РґРµР»СЊС†Р°, РІСЃС‚СЂРѕРµРЅРЅР°СЏ РёР»Рё РЅР°СЃС‚СЂРѕР№РєРё РЅР°РїСЂСЏРјСѓСЋ; style вЂ” РґРѕРїРѕР»РЅРµРЅРёРµ СЃР»РѕРІР°РјРё.
    Р’ РєР°РјРїР°РЅРёСЋ РїРёС€РµС‚СЃСЏ РєРѕРїРёСЏ: Рё РіРѕС‚РѕРІС‹Р№ Р°Р±Р·Р°С† СЃС‚РёР»СЏ РґР»СЏ РїСЂРѕРјРїС‚Р°, Рё СЃР°РјРё РЅР°СЃС‚СЂРѕР№РєРё РґР»СЏ РїРѕРєР°Р·Р° Рё РїСЂР°РІРєРё."""
    name, source, settings = None, None, None
    if choice.get("persona_id"):
        p = await session.get(MasterPersona, choice["persona_id"])
        if p is None or p.user_id != owner.id:
            raise NotFound("РїРµСЂСЃРѕРЅР° РјР°СЃС‚РµСЂР° РЅРµ РЅР°Р№РґРµРЅР°")
        name, source, settings = p.name, "profile", dict(p.settings)
    elif choice.get("preset") or choice.get("persona_preset"):
        preset = personas.preset(choice.get("preset") or choice.get("persona_preset"))
        if preset is None:
            raise NotFound("РІСЃС‚СЂРѕРµРЅРЅР°СЏ РїРµСЂСЃРѕРЅР° РЅРµ РЅР°Р№РґРµРЅР°")
        name, source, settings = preset["name"], "preset", dict(preset["settings"])
    elif choice.get("settings") or choice.get("persona"):
        name, source, settings = None, "custom", dict(choice.get("settings") or choice.get("persona"))
    style = (choice.get("style") or "").strip() or None
    meta = dict(agent.settings or {})
    if settings is None:
        agent.persona = style
        meta.pop("persona", None)
    else:
        agent.persona = personas.compose_style(settings, style)
        meta["persona"] = {"name": name, "source": source, "settings": settings, "style": style}
    agent.settings = meta


def has_persona_choice(master: dict) -> bool:
    return any(master.get(k) for k in ("persona_id", "persona_preset", "persona", "preset", "settings"))


async def apply_master_preset(
    session: AsyncSession, agent: AgentConfig, preset: MasterPreset, owner: User | None = None
) -> AgentConfig:
    """РџСЂРёРјРµРЅСЏРµС‚ РїСЂРµСЃРµС‚ РјР°СЃС‚РµСЂР° (РјРѕРґРµР»СЊ, С‚РѕРЅ, С…Р°СЂР°РєС‚РµСЂ) Рє РєРѕРЅС„РёРіСѓСЂР°С†РёРё Р°РіРµРЅС‚Р°."""
    if preset.model_profile_id:
        profile = await session.get(ModelProfile, preset.model_profile_id)
        if profile is not None:
            apply_model(agent, profile.provider, profile.model, profile.temperature, profile.api_base, profile.id)
    choice = {}
    if preset.persona_id:
        choice["persona_id"] = preset.persona_id
    elif preset.persona_preset:
        choice["preset"] = preset.persona_preset
    elif preset.persona_settings:
        choice["settings"] = preset.persona_settings
    if preset.style:
        choice["style"] = preset.style
    u = owner or (await session.get(User, preset.user_id))
    if u is not None and (has_persona_choice(choice) or choice.get("style")):
        await apply_persona(session, u, agent, choice)
    elif preset.style:
        agent.persona = preset.style
    if preset.character:
        agent.settings = {
            **(agent.settings or {}),
            "character": persona.normalize(preset.character, master=True),
        }
    return agent


async def agent_for_master(
    session: AsyncSession, master: dict, agent: AgentConfig | None = None, owner: User | None = None
) -> AgentConfig:
    agent = agent or AgentConfig(settings={})
    preset_id = master.get("preset_id")
    if preset_id:
        preset = await session.get(MasterPreset, preset_id)
        if preset is not None:
            await apply_master_preset(session, agent, preset, owner=owner)

    temperature = master.get("temperature")
    if temperature is not None:
        agent.temperature = float(temperature)

    agent.provider = "env"
    agent.model = "env"

    if owner is not None and has_persona_choice(master):
        await apply_persona(session, owner, agent, master)
    elif "style" in master and master["style"]:
        agent.persona = master.get("style")

    if "character" in master and master["character"]:
        agent.settings = {
            **(agent.settings or {}),
            "character": persona.normalize(master["character"], master=True),
        }
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
    brief: dict | None = None,
) -> Campaign:
    if not is_admin(owner):
        raise AccessDenied("РєР°РјРїР°РЅРёРё СЃРѕР·РґР°С‘С‚ С‚РѕР»СЊРєРѕ Admin")
    if difficulty not in DIFFICULTIES:
        raise Conflict(f"СЃР»РѕР¶РЅРѕСЃС‚СЊ РѕРґРЅР° РёР·: {', '.join(DIFFICULTIES)}")
    rec = party_size(pack, difficulty)
    count = players if players is not None else rec["recommended"]
    if not 1 <= count <= MAX_PLAYERS:
        raise Conflict(f"РёРіСЂРѕРєРѕРІ РѕС‚ 1 РґРѕ {MAX_PLAYERS}")

    master_type = master.get("type")
    if master_type == "owner":
        m = Seat(role="master", position=0, occupant_type="human", user_id=owner.id, joined_at=now())
    elif master_type == "agent":
        agent = await agent_for_master(session, master, owner=owner)
        session.add(agent)
        await session.flush()
        m = Seat(role="master", position=0, occupant_type="agent", agent_config_id=agent.id, joined_at=now())
    else:
        raise Conflict("РјР°СЃС‚РµСЂ: {type: owner} РёР»Рё {type: agent, provider, model}")

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
        brief=brief or {},
        seats=[m, *(Seat(role="player", position=i) for i in range(1, count + 1))],
    )
    if master_type != "owner" and owner_plays:
        # РІР»Р°РґРµР»РµС†, РєРѕС‚РѕСЂС‹Р№ РЅРµ РІРµРґС‘С‚ РёРіСЂСѓ СЃР°Рј, СЃСЂР°Р·Сѓ СЃР°РґРёС‚СЃСЏ РЅР° РїРµСЂРІРѕРµ РјРµСЃС‚Рѕ РёРіСЂРѕРєР°
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
        raise AccessDenied("РїСЂРёРіР»Р°С€Р°С‚СЊ РјРѕР¶РµС‚ С‚РѕР»СЊРєРѕ РІР»Р°РґРµР»РµС†")
    invite = Invite(campaign_id=viewer.campaign.id, created_by=viewer.user.id, expires_at=expires_at, max_uses=max_uses)
    session.add(invite)
    await session.flush()
    return invite


def invite_problem(invite: Invite | None) -> str | None:
    if invite is None or invite.revoked:
        return "РїСЂРёРіР»Р°С€РµРЅРёРµ РЅРµРґРµР№СЃС‚РІРёС‚РµР»СЊРЅРѕ"
    exp = as_utc(invite.expires_at)
    if exp is not None and exp <= datetime.now(UTC):
        return "СЃСЂРѕРє РїСЂРёРіР»Р°С€РµРЅРёСЏ РёСЃС‚С‘Рє"
    if invite.max_uses is not None and invite.uses >= invite.max_uses:
        return "РїСЂРёРіР»Р°С€РµРЅРёРµ СѓР¶Рµ РёСЃРїРѕР»СЊР·РѕРІР°РЅРѕ"
    return None


async def accept_invite(session: AsyncSession, user: User, token: str) -> Seat:
    """РЎР°Р¶Р°РµС‚ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РЅР° РїРµСЂРІРѕРµ СЃРІРѕР±РѕРґРЅРѕРµ РјРµСЃС‚Рѕ РёРіСЂРѕРєР°."""
    invite = await session.get(Invite, token, with_for_update=True)
    problem = invite_problem(invite)
    if problem:
        raise Conflict(problem)
    campaign = await session.get(Campaign, invite.campaign_id)
    if campaign.status == "ended":
        raise Conflict("РєР°РјРїР°РЅРёСЏ Р·Р°РІРµСЂС€РµРЅР°")
    existing = seat_for(campaign, user.id)
    if existing is not None:
        if existing.role == "master":
            raise Conflict("РјР°СЃС‚РµСЂ РЅРµ Р·Р°РЅРёРјР°РµС‚ РјРµСЃС‚Рѕ РёРіСЂРѕРєР°")
        return existing
    free = next((s for s in campaign.seats if s.role == "player" and s.occupant_type == "empty"), None)
    if free is None:
        raise Conflict("СЃРІРѕР±РѕРґРЅС‹С… РјРµСЃС‚ РЅРµС‚")
    free.occupant_type, free.user_id, free.joined_at = "human", user.id, now()
    invite.uses += 1
    await inherit_hero(session, free, user.id)
    await session.flush()
    return free


async def take_seat(session: AsyncSession, viewer: Viewer) -> Seat:
    """Р’Р»Р°РґРµР»РµС† СЃР°РґРёС‚СЃСЏ РЅР° СЃРІРѕР±РѕРґРЅРѕРµ РјРµСЃС‚Рѕ РёРіСЂРѕРєР° РІ СЃРІРѕРµР№ РєР°РјРїР°РЅРёРё (Р±РµР· РїСЂРёРіР»Р°С€РµРЅРёСЏ)."""
    if not viewer.is_owner:
        raise AccessDenied("Р·Р°РЅСЏС‚СЊ РјРµСЃС‚Рѕ Р±РµР· РїСЂРёРіР»Р°С€РµРЅРёСЏ РјРѕР¶РµС‚ С‚РѕР»СЊРєРѕ РІР»Р°РґРµР»РµС†")
    if viewer.seat is not None:
        raise Conflict("РІС‹ СѓР¶Рµ РЅР° РјРµСЃС‚Рµ " + ("РјР°СЃС‚РµСЂР°" if viewer.is_master else "РёРіСЂРѕРєР°"))
    free = next((s for s in viewer.campaign.seats if s.role == "player" and s.occupant_type == "empty"), None)
    if free is None:
        raise Conflict("СЃРІРѕР±РѕРґРЅС‹С… РјРµСЃС‚ РЅРµС‚")
    free.occupant_type, free.user_id, free.joined_at = "human", viewer.user.id, now()
    await inherit_hero(session, free, viewer.user.id)
    await session.flush()
    return free


async def inherit_hero(session: AsyncSession, seat: Seat, user_id: str) -> None:
    """Р–РёРІРѕР№ РёРіСЂРѕРє СЃРµР» РЅР° РјРµСЃС‚Рѕ, РіРґРµ РѕСЃС‚Р°Р»СЃСЏ РіРµСЂРѕР№ (РР-РёРіСЂРѕРєР° РёР»Рё РёСЃРєР»СЋС‡С‘РЅРЅРѕРіРѕ): РіРµСЂРѕР№ С‚РµРїРµСЂСЊ РµРіРѕ."""
    from app.db.models import Character

    q = select(Character).where(Character.seat_id == seat.id, Character.status.in_(("approved", "active")))
    for ch in (await session.scalars(q)).all():
        ch.owner_user_id = user_id


async def seat_agent(session: AsyncSession, viewer: Viewer, seat_id: str, model_profile_id: str | None) -> Seat:
    """РР-РёРіСЂРѕРє РЅР° РїСѓСЃС‚РѕРј РјРµСЃС‚Рµ (СЂР°Р·РґРµР» 5.2): РјРѕРґРµР»СЊ РёР· РїСЂРѕС„РёР»СЏ Р°РґРјРёРЅРєРё РёР»Рё РїСЂРѕС„РёР»СЊ РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ."""
    if not viewer.is_owner:
        raise AccessDenied("СЃР°Р¶Р°С‚СЊ РР-РёРіСЂРѕРєРѕРІ РјРѕР¶РµС‚ С‚РѕР»СЊРєРѕ РІР»Р°РґРµР»РµС†")
    seat = next((s for s in viewer.campaign.seats if s.id == seat_id), None)
    if seat is None or seat.role != "player":
        raise NotFound("РјРµСЃС‚Рѕ РёРіСЂРѕРєР° РЅРµ РЅР°Р№РґРµРЅРѕ")
    if seat.occupant_type != "empty":
        raise Conflict("РјРµСЃС‚Рѕ Р·Р°РЅСЏС‚Рѕ: СЃРЅР°С‡Р°Р»Р° РѕСЃРІРѕР±РѕРґРёС‚Рµ РµРіРѕ")
    agent = await agent_for_master(session, {"model_profile_id": model_profile_id} if model_profile_id else {})
    agent.settings = {**(agent.settings or {}), "role": "player"}
    session.add(agent)
    await session.flush()
    seat.occupant_type, seat.agent_config_id, seat.joined_at = "agent", agent.id, now()
    await session.flush()
    return seat


async def free_seat(session: AsyncSession, viewer: Viewer, seat_id: str) -> Seat:
    """РСЃРєР»СЋС‡РµРЅРёРµ РёРіСЂРѕРєР°: РјРµСЃС‚Рѕ РѕСЃРІРѕР±РѕР¶РґР°РµС‚СЃСЏ, РїРµСЂСЃРѕРЅР°Р¶ РѕСЃС‚Р°С‘С‚СЃСЏ Р·Р° РјРµСЃС‚РѕРј (СЌС‚Р°Рї 3)."""
    if not viewer.can_manage_members:
        raise AccessDenied("РёСЃРєР»СЋС‡Р°С‚СЊ РјРѕР¶РµС‚ С‚РѕР»СЊРєРѕ РІР»Р°РґРµР»РµС†")
    seat = next((s for s in viewer.campaign.seats if s.id == seat_id), None)
    if seat is None:
        raise NotFound("РјРµСЃС‚Рѕ РЅРµ РЅР°Р№РґРµРЅРѕ")
    if seat.role == "master":
        raise Conflict("РјРµСЃС‚Рѕ РјР°СЃС‚РµСЂР° С‚Р°Рє РЅРµ РѕСЃРІРѕР±РѕР¶РґР°РµС‚СЃСЏ")
    seat.occupant_type, seat.user_id, seat.agent_config_id, seat.joined_at = "empty", None, None, None
    seat.delegated_from = seat.stand_in_user_id = None
    await session.flush()
    return seat


async def leave_campaign(session: AsyncSession, viewer: Viewer) -> None:
    if viewer.seat is None or viewer.seat.role != "player":
        raise Conflict("РїРѕРєРёРЅСѓС‚СЊ РєР°РјРїР°РЅРёСЋ РјРѕР¶РµС‚ С‚РѕР»СЊРєРѕ РёРіСЂРѕРє")
    s = viewer.seat
    s.occupant_type, s.user_id, s.joined_at = "empty", None, None
    await session.flush()

