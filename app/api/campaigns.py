from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.agents import memory
from app.agents.llm import LLMError, model_for
from app.api.deps import SessionDep, SettingsDep, UserDep
from app.api.schemas import (
    CampaignCreateIn,
    CampaignOut,
    CampaignPatchIn,
    CampaignPersonaOut,
    InviteCreateIn,
    InviteOut,
    InvitePreviewOut,
    MasterCharacterIn,
    MasterModelIn,
    MasterModelOut,
    MasterPresetOut,
    MasterPresetSaveFromCampaignIn,
    PersonaChoiceIn,
    SeatOut,
    SecretsIn,
)
from app.content.catalog import CatalogError, resolve_chain
from app.content.importer import latest_version
from app.core import audio, chat, master_log
from app.core import campaigns as svc
from app.core.campaigns import AccessDenied, Conflict, NotFound, Viewer
from app.core.world import get_scene
from app.db.models import AgentConfig, Campaign, CampaignSecret, ContentPack, Invite, MasterPreset, ModelProfile, User
from app.gateway.events import envelope, publish_message
from app.rules.dnd5e import Dnd5eEngine

router = APIRouter(prefix="/api", tags=["campaigns"])


async def campaign_out(session, campaign: Campaign, user: User) -> CampaignOut:
    agent_ids = [s.agent_config_id for s in campaign.seats if s.agent_config_id]
    providers = {}
    if agent_ids:
        rows = (await session.scalars(select(AgentConfig).where(AgentConfig.id.in_(agent_ids)))).all()
        providers = {a.id: a.provider for a in rows}
    mine = svc.seat_for(campaign, user.id)
    return CampaignOut(
        id=campaign.id,
        name=campaign.name,
        status=campaign.status,
        owner_id=campaign.owner_id,
        is_owner=campaign.owner_id == user.id,
        my_seat_id=mine.id if mine else None,
        my_role=mine.role if mine else None,
        ruleset_id=campaign.ruleset_id,
        ruleset_version=campaign.ruleset_version,
        pack_id=campaign.pack_id,
        pack_version=campaign.pack_version,
        difficulty=campaign.difficulty,
        party_size_recommended=campaign.party_size_recommended,
        public_intro=campaign.public_intro,
        settings=campaign.settings,
        brief=campaign.brief if campaign.owner_id == user.id or (mine and mine.role == "master") else None,
        seats=[
            SeatOut(
                id=s.id,
                role=s.role,
                position=s.position,
                occupant_type=s.occupant_type,
                user_id=s.user_id,
                user_name=s.user.name if s.user else None,
                agent_provider=providers.get(s.agent_config_id),
            )
            for s in campaign.seats
        ],
        created_at=campaign.created_at,
    )


def invite_out(invite: Invite, public_url: str) -> InviteOut:
    return InviteOut(
        token=invite.token,
        url=f"{public_url}/invite/{invite.token}",
        campaign_id=invite.campaign_id,
        expires_at=invite.expires_at,
        max_uses=invite.max_uses,
        uses=invite.uses,
        revoked=invite.revoked,
    )


async def _viewer(session, user: User, campaign_id: str) -> Viewer:
    return await svc.get_viewer(session, user, campaign_id)


# --- РљР°РјРїР°РЅРёРё ---


@router.get("/campaigns")
async def list_campaigns(user: UserDep, session: SessionDep) -> list[CampaignOut]:
    return [await campaign_out(session, c, user) for c in await svc.list_campaigns(session, user)]


@router.get("/party-size")
async def recommend_party(
    user: UserDep, session: SessionDep, difficulty: str = "normal", pack_id: str | None = None
) -> dict:
    """Р РµРєРѕРјРµРЅРґР°С†РёСЏ СЂР°Р·РјРµСЂР° РѕС‚СЂСЏРґР° РґР»СЏ РјР°СЃС‚РµСЂР° СЃРѕР·РґР°РЅРёСЏ РєР°РјРїР°РЅРёРё (СЂР°Р·РґРµР» 5.2)."""
    pack = await latest_version(session, pack_id) if pack_id else None
    return svc.party_size(pack, difficulty)


@router.post("/campaigns", status_code=201)
async def create_campaign(body: CampaignCreateIn, user: UserDep, session: SessionDep) -> CampaignOut:
    pack = None
    if body.pack_id:
        pack = (
            await session.get(ContentPack, (body.pack_id, body.pack_version))
            if body.pack_version
            else await latest_version(session, body.pack_id)
        )
        if pack is None:
            raise NotFound("РїР°РєРµС‚ РЅРµ РёРјРїРѕСЂС‚РёСЂРѕРІР°РЅ")
        if pack.manifest.get("ruleset") != "dnd5e":
            raise Conflict("РїР°РєРµС‚ РґР»СЏ РґСЂСѓРіРѕР№ СЃРёСЃС‚РµРјС‹ РїСЂР°РІРёР»")
    campaign = await svc.create_campaign(
        session,
        user,
        name=body.name,
        ruleset_version=Dnd5eEngine.version,
        pack=pack,
        difficulty=body.difficulty,
        players=body.players,
        master=body.master.model_dump(),
        public_intro=body.public_intro,
        settings={
            "turn_timeout_sec": body.turn_timeout_sec,
            "spend_limit_usd": body.spend_limit_usd,
            "collect_window_sec": body.collect_window_sec,
            "excluded_themes": body.excluded_themes,
            "creation_rules": body.creation_rules.model_dump(),
            "allow_proposals": body.test_mode,
            "leveling": body.leveling,
            "tts_provider": body.tts_provider,
            "tts_enabled": body.tts_enabled,
            "tts_voice": body.tts_voice,
        },
        owner_plays=body.owner_plays,
        brief=body.brief.model_dump(exclude_defaults=True),
    )
    try:
        campaign.content_chain = await resolve_chain(session, pack)
    except CatalogError as e:
        if pack is not None:
            raise Conflict(str(e)) from None
        # Р±РµР· РїР°РєРµС‚Р° РјРёСЂР° С†РµРїРѕС‡РєР° вЂ” Р±Р°Р·РѕРІС‹Р№ РїР°РєРµС‚ РїСЂР°РІРёР»; РµСЃР»Рё РѕРЅ РµС‰С‘ РЅРµ РёРјРїРѕСЂС‚РёСЂРѕРІР°РЅ, РµС‘ РЅР°Р№РґСѓС‚ РїСЂРё РїРµСЂРІРѕР№ РёРіСЂРµ
    await session.commit()
    return await campaign_out(session, campaign, user)


@router.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str, user: UserDep, session: SessionDep) -> CampaignOut:
    v = await _viewer(session, user, campaign_id)
    return await campaign_out(session, v.campaign, user)


@router.patch("/campaigns/{campaign_id}")
async def patch_campaign(
    campaign_id: str, body: CampaignPatchIn, user: UserDep, session: SessionDep, request: Request
) -> CampaignOut:
    v = await _viewer(session, user, campaign_id)
    if not v.is_owner:
        raise AccessDenied("РјРµРЅСЏС‚СЊ РєР°РјРїР°РЅРёСЋ РјРѕР¶РµС‚ С‚РѕР»СЊРєРѕ РІР»Р°РґРµР»РµС†")
    c = v.campaign
    if body.name is not None:
        c.name = body.name
    if body.public_intro is not None:
        c.public_intro = body.public_intro
    if body.difficulty is not None:
        c.difficulty = body.difficulty
    settings = dict(c.settings)
    for key in (
        "turn_timeout_sec",
        "spend_limit_usd",
        "collect_window_sec",
        "excluded_themes",
        "audio_enabled",
        "tts_provider",
        "tts_enabled",
        "tts_voice",
        "leveling",
        "random_events",
    ):
        if key in body.model_fields_set and (
            key not in ("leveling", "random_events") or getattr(body, key) is not None
        ):
            settings[key] = getattr(body, key)
    sound = bool(settings.get("audio_enabled")) != bool((c.settings or {}).get("audio_enabled"))
    c.settings = settings
    if body.brief is not None:
        c.brief = body.brief.model_dump(exclude_defaults=True)
    await session.commit()
    if sound:  # Р·РІСѓРє РІРєР»СЋС‡РёР»Рё РёР»Рё РІС‹РєР»СЋС‡РёР»Рё РїРѕСЃСЂРµРґРё РёРіСЂС‹: Сѓ РёРіСЂРѕРєРѕРІ РѕРЅ Р·Р°РёРіСЂР°РµС‚ РёР»Рё СЃРјРѕР»РєРЅРµС‚ СЃСЂР°Р·Сѓ
        sc = await get_scene(session, c.id)
        env = envelope("audio.state", c.id, {**audio.public_state(c, sc), "cues": []})
        await request.app.state.bus.publish(c.id, env, None)
    return await campaign_out(session, c, user)


async def _master_agent(session, user: User, campaign_id: str, what: str = "РјРѕРґРµР»СЊ РјР°СЃС‚РµСЂР°") -> AgentConfig:
    v = await _viewer(session, user, campaign_id)
    if not v.is_owner:
        raise AccessDenied(f"{what} РјРµРЅСЏРµС‚ С‚РѕР»СЊРєРѕ РІР»Р°РґРµР»РµС† РєР°РјРїР°РЅРёРё")
    seat = next((s for s in v.campaign.seats if s.role == "master"), None)
    agent = await session.get(AgentConfig, seat.agent_config_id) if seat and seat.agent_config_id else None
    if agent is None:
        raise Conflict("РјР°СЃС‚РµСЂ СЌС‚РѕР№ РєР°РјРїР°РЅРёРё вЂ” С‡РµР»РѕРІРµРє, Р° РЅРµ РР")
    return agent


async def master_model_out(session, agent: AgentConfig) -> MasterModelOut:
    extra = agent.settings or {}
    profile = await session.get(ModelProfile, extra["model_profile_id"]) if extra.get("model_profile_id") else None
    try:
        resolved = model_for()
    except LLMError:
        resolved = None
    return MasterModelOut(
        provider=agent.provider,
        model=agent.model,
        resolved_model=resolved,
        temperature=agent.temperature,
        api_base=extra.get("api_base"),
        model_profile_id=profile.id if profile else None,
        model_profile_name=profile.name if profile else None,
    )


@router.get("/campaigns/{campaign_id}/master-model")
async def get_master_model(campaign_id: str, user: UserDep, session: SessionDep) -> MasterModelOut:
    return await master_model_out(session, await _master_agent(session, user, campaign_id))


@router.put("/campaigns/{campaign_id}/master-model")
async def put_master_model(campaign_id: str, body: MasterModelIn, user: UserDep, session: SessionDep) -> MasterModelOut:
    """РЎРјРµРЅРёС‚СЊ РјРѕРґРµР»СЊ РР-РјР°СЃС‚РµСЂР°: СЃР»РµРґСѓСЋС‰РёР№ С…РѕРґ РјР°СЃС‚РµСЂ СЃРґРµР»Р°РµС‚ СѓР¶Рµ РЅРѕРІРѕР№ РјРѕРґРµР»СЊСЋ."""
    agent = await _master_agent(session, user, campaign_id)
    if not body.model_profile_id and not body.provider:
        raise Conflict("РІС‹Р±РµСЂРёС‚Рµ РїСЂРѕС„РёР»СЊ РјРѕРґРµР»Рё РёР»Рё РїСЂРѕРІР°Р№РґРµСЂР°")
    await svc.agent_for_master(session, body.model_dump(), agent)
    await session.commit()
    return await master_model_out(session, agent)


def persona_out(agent: AgentConfig) -> CampaignPersonaOut:
    meta = (agent.settings or {}).get("persona")
    if not meta:
        return CampaignPersonaOut(
            name=None, source="legacy" if agent.persona else None, settings=None, style=agent.persona
        )
    return CampaignPersonaOut(
        name=meta.get("name"), source=meta.get("source"), settings=meta.get("settings"), style=meta.get("style")
    )


@router.get("/campaigns/{campaign_id}/master-persona")
async def get_master_persona(campaign_id: str, user: UserDep, session: SessionDep) -> CampaignPersonaOut:
    return persona_out(await _master_agent(session, user, campaign_id, "С…Р°СЂР°РєС‚РµСЂ РјР°СЃС‚РµСЂР°"))


@router.put("/campaigns/{campaign_id}/master-persona")
async def put_master_persona(
    campaign_id: str, body: PersonaChoiceIn, user: UserDep, session: SessionDep
) -> CampaignPersonaOut:
    """РЎРјРµРЅРёС‚СЊ С…Р°СЂР°РєС‚РµСЂ РР-РјР°СЃС‚РµСЂР°: СЃР»РµРґСѓСЋС‰РёР№ С…РѕРґ РјР°СЃС‚РµСЂ РІРµРґС‘С‚ СѓР¶Рµ РІ РЅРѕРІРѕРј С‚РѕРЅРµ."""
    agent = await _master_agent(session, user, campaign_id, "С…Р°СЂР°РєС‚РµСЂ РјР°СЃС‚РµСЂР°")
    await svc.apply_persona(session, user, agent, body.model_dump())
    await session.commit()
    return persona_out(agent)


# --- С…Р°СЂР°РєС‚РµСЂ РР-РјР°СЃС‚РµСЂР° (СЌС‚Р°Рї 9Р±): Р°РЅРєРµС‚Р°, РїРѕРјРѕС‰РЅРёРє, РїСЂРѕРІРµСЂРєР°, Р»РµС‚РѕРїРёСЃСЊ ---


class MasterDraftIn(BaseModel):
    persona: MasterCharacterIn | None = None


class MasterNoteIn(BaseModel):
    text: str | None = None
    cause: str | None = None
    reverted: bool | None = None


async def _master_character_out(session, campaign_id: str, agent: AgentConfig) -> dict:
    from app.core import persona

    notes = await persona.notes_of(session, campaign_id, None)
    return {
        "persona": persona.normalize((agent.settings or {}).get("character"), master=True),
        "schema": persona.schema(master=True),
        "notes": [persona.note_out(n) for n in notes],
        "can_edit": True,
    }


@router.get("/campaigns/{campaign_id}/master-character")
async def get_master_character(campaign_id: str, user: UserDep, session: SessionDep) -> dict:
    agent = await _master_agent(session, user, campaign_id, "С…Р°СЂР°РєС‚РµСЂ РјР°СЃС‚РµСЂР°")
    return await _master_character_out(session, campaign_id, agent)


@router.put("/campaigns/{campaign_id}/master-character")
async def put_master_character(campaign_id: str, body: MasterCharacterIn, user: UserDep, session: SessionDep) -> dict:
    """РЎРІРѕР±РѕРґРЅС‹Р№ С‚РµРєСЃС‚ Рё РїРѕР»СЏ С…Р°СЂР°РєС‚РµСЂР° РР-РјР°СЃС‚РµСЂР°: РІ РїРѕРґСЃРєР°Р·РєСѓ РјР°СЃС‚РµСЂР° СЃРѕ СЃР»РµРґСѓСЋС‰РµРіРѕ С…РѕРґР°."""
    from app.core import persona

    agent = await _master_agent(session, user, campaign_id, "С…Р°СЂР°РєС‚РµСЂ РјР°СЃС‚РµСЂР°")
    agent.settings = {**(agent.settings or {}), "character": persona.normalize(body.model_dump(), master=True)}
    await session.commit()
    return await _master_character_out(session, campaign_id, agent)


async def _master_draft(session, user, campaign_id: str, body: MasterDraftIn) -> dict:
    agent = await _master_agent(session, user, campaign_id, "С…Р°СЂР°РєС‚РµСЂ РјР°СЃС‚РµСЂР°")
    sheet = body.persona.model_dump() if body.persona else dict((agent.settings or {}).get("character") or {})
    await session.rollback()  # РјРѕРґРµР»СЊ РґСѓРјР°РµС‚ РґРѕР»РіРѕ: Р±Р°Р·Сѓ РЅРµ РґРµСЂР¶РёРј
    return sheet


@router.post("/campaigns/{campaign_id}/master-character/help")
async def help_master_character(
    campaign_id: str, body: MasterDraftIn, user: UserDep, session: SessionDep, request: Request
) -> dict:
    from app.agents import character

    sheet = await _master_draft(session, user, campaign_id, body)
    return {"persona": await character.help_fill(request.app.state.master, campaign_id, sheet, character_id=None)}


@router.post("/campaigns/{campaign_id}/master-character/test")
async def test_master_character(
    campaign_id: str, body: MasterDraftIn, user: UserDep, session: SessionDep, request: Request
) -> dict:
    """РџСЂРѕР±РЅС‹Рµ СЃС†РµРЅС‹ РјР°СЃС‚РµСЂР°: РѕРїРёСЃР°РЅРёРµ РјРµСЃС‚Р°, СЂРµР°РєС†РёСЏ NPC, РїСЂРѕРІР°Р» РіРµСЂРѕСЏ."""
    from app.agents import character

    sheet = await _master_draft(session, user, campaign_id, body)
    return {"scenes": await character.try_scenes(request.app.state.master, campaign_id, sheet, character_id=None)}


@router.patch("/campaigns/{campaign_id}/master-character/notes/{note_id}")
async def patch_master_note(
    campaign_id: str, note_id: str, body: MasterNoteIn, user: UserDep, session: SessionDep
) -> dict:
    from app.core import persona
    from app.db.models import PersonaNote

    agent = await _master_agent(session, user, campaign_id, "Р»РµС‚РѕРїРёСЃСЊ РјР°СЃС‚РµСЂР°")
    n = await session.get(PersonaNote, note_id)
    if n is None or n.campaign_id != campaign_id or n.character_id is not None:
        raise Conflict("Р·Р°РїРёСЃСЊ Р»РµС‚РѕРїРёСЃРё РЅРµ РЅР°Р№РґРµРЅР°")
    persona.edit_note(n, body.text, body.cause, body.reverted)
    await session.commit()
    return await _master_character_out(session, campaign_id, agent)


@router.post("/campaigns/{campaign_id}/save-master-preset")
async def save_campaign_master_preset(
    campaign_id: str, body: MasterPresetSaveFromCampaignIn, user: UserDep, session: SessionDep
) -> MasterPresetOut:
    """РЎРѕС…СЂР°РЅСЏРµС‚ С‚РµРєСѓС‰СѓСЋ РєРѕРЅС„РёРіСѓСЂР°С†РёСЋ РјР°СЃС‚РµСЂР° (РјРѕРґРµР»СЊ, С‚РѕРЅ, Р°РЅРєРµС‚Р° С…Р°СЂР°РєС‚РµСЂР°) РєР°Рє РїСЂРµСЃРµС‚."""
    from app.api.personas import preset_name_taken, preset_out

    agent = await _master_agent(session, user, campaign_id, "РїСЂРµСЃРµС‚ РјР°СЃС‚РµСЂР°")
    extra = dict(agent.settings or {})
    persona_meta = extra.get("persona") or {}
    char_data = extra.get("character") or {}

    name = body.name.strip()
    if body.preset_id:
        preset = await session.get(MasterPreset, body.preset_id)
        if preset is None or preset.user_id != user.id:
            raise NotFound("РїСЂРµСЃРµС‚ РЅРµ РЅР°Р№РґРµРЅ")
        if await preset_name_taken(session, user, name, except_id=preset.id):
            raise Conflict("РїСЂРµСЃРµС‚ СЃ С‚Р°РєРёРј РЅР°Р·РІР°РЅРёРµРј СѓР¶Рµ РµСЃС‚СЊ")
        preset.name = name
        preset.model_profile_id = extra.get("model_profile_id")
        preset.persona_id = persona_meta.get("persona_id") if persona_meta.get("source") == "profile" else None
        preset.persona_preset = persona_meta.get("preset") if persona_meta.get("source") == "preset" else None
        preset.persona_settings = persona_meta.get("settings") or {}
        preset.style = persona_meta.get("style") or agent.persona
        preset.character = char_data
    else:
        if await preset_name_taken(session, user, name):
            raise Conflict("РїСЂРµСЃРµС‚ СЃ С‚Р°РєРёРј РЅР°Р·РІР°РЅРёРµРј СѓР¶Рµ РµСЃС‚СЊ")
        preset = MasterPreset(
            user_id=user.id,
            name=name,
            model_profile_id=extra.get("model_profile_id"),
            persona_id=persona_meta.get("persona_id") if persona_meta.get("source") == "profile" else None,
            persona_preset=persona_meta.get("preset") if persona_meta.get("source") == "preset" else None,
            persona_settings=persona_meta.get("settings") or {},
            style=persona_meta.get("style") or agent.persona,
            character=char_data,
        )
        session.add(preset)

    await session.commit()
    return await preset_out(session, preset)


@router.post("/campaigns/{campaign_id}/apply-master-preset/{preset_id}")
async def apply_campaign_master_preset(campaign_id: str, preset_id: str, user: UserDep, session: SessionDep) -> dict:
    """РџСЂРёРјРµРЅСЏРµС‚ СЃРѕС…СЂР°РЅС‘РЅРЅС‹Р№ РїСЂРµСЃРµС‚ Рє РР-РјР°СЃС‚РµСЂСѓ РєР°РјРїР°РЅРёРё."""
    agent = await _master_agent(session, user, campaign_id, "РїСЂРµСЃРµС‚ РјР°СЃС‚РµСЂР°")
    preset = await session.get(MasterPreset, preset_id)
    if preset is None or preset.user_id != user.id:
        raise NotFound("РїСЂРµСЃРµС‚ РјР°СЃС‚РµСЂР° РЅРµ РЅР°Р№РґРµРЅ")
    await svc.apply_master_preset(session, agent, preset, owner=user)
    await session.commit()
    return {
        "ok": True,
        "model": await master_model_out(session, agent),
        "persona": persona_out(agent),
        "character": await _master_character_out(session, campaign_id, agent),
    }


@router.delete("/campaigns/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: str, user: UserDep, session: SessionDep, request: Request) -> Response:
    v = await _viewer(session, user, campaign_id)
    if not v.is_owner:
        raise AccessDenied("СѓРґР°Р»РёС‚СЊ РєР°РјРїР°РЅРёСЋ РјРѕР¶РµС‚ С‚РѕР»СЊРєРѕ РІР»Р°РґРµР»РµС†")
    await session.delete(v.campaign)
    await session.commit()
    await request.app.state.bus.publish(campaign_id, envelope("campaign.deleted", campaign_id, {}), None)
    return Response(status_code=204)


# --- РЎРєСЂС‹С‚С‹Рµ РґР°РЅРЅС‹Рµ РјР°СЃС‚РµСЂР° ---


@router.get("/campaigns/{campaign_id}/secrets")
async def get_secrets(campaign_id: str, user: UserDep, session: SessionDep) -> dict:
    """РўРѕР»СЊРєРѕ РјРµСЃС‚Рѕ РјР°СЃС‚РµСЂР°. Р’Р»Р°РґРµР»РµС† Р±РµР· РјРµСЃС‚Р° РјР°СЃС‚РµСЂР° РёС… РЅРµ РІРёРґРёС‚ (СЂР°Р·РґРµР» 2)."""
    v = await _viewer(session, user, campaign_id)
    if not v.is_master:
        raise NotFound("РЅРµС‚ РґРѕСЃС‚СѓРїР°")
    s = await session.get(CampaignSecret, campaign_id)
    return {"setting": s.setting, "plot": s.plot}


@router.put("/campaigns/{campaign_id}/secrets")
async def put_secrets(campaign_id: str, body: SecretsIn, user: UserDep, session: SessionDep) -> dict:
    v = await _viewer(session, user, campaign_id)
    if not v.is_master:
        raise NotFound("РЅРµС‚ РґРѕСЃС‚СѓРїР°")
    s = await session.get(CampaignSecret, campaign_id)
    if body.setting is not None:
        s.setting = body.setting
    if body.plot is not None:
        s.plot = body.plot
    await session.commit()
    return {"setting": s.setting, "plot": s.plot}


@router.get("/campaigns/{campaign_id}/master-panel")
async def get_master_panel(campaign_id: str, user: UserDep, session: SessionDep) -> dict:
    """Р¤РѕСЂРјС‹ РёРЅСЃС‚СЂСѓРјРµРЅС‚РѕРІ РґР»СЏ Р¶РёРІРѕРіРѕ РјР°СЃС‚РµСЂР°: СЃС…РµРјС‹, РґРѕРїСѓСЃС‚РёРјС‹Рµ Р·РЅР°С‡РµРЅРёСЏ Рё РїРѕРґРїРёСЃРё Рє id. РўРѕР»СЊРєРѕ РјРµСЃС‚Рѕ РјР°СЃС‚РµСЂР°."""
    from app.content.catalog import campaign_catalog
    from app.core.master_panel import panel
    from app.core.world import load_world

    v = await _viewer(session, user, campaign_id)
    if not v.is_master:
        raise NotFound("РЅРµС‚ РґРѕСЃС‚СѓРїР°")
    world = await load_world(session, v.campaign, await campaign_catalog(session, v.campaign))
    return panel(world)


# --- Р–СѓСЂРЅР°Р» РјР°СЃС‚РµСЂР° ---


@router.get("/campaigns/{campaign_id}/master-log")
async def get_master_log(
    campaign_id: str, user: UserDep, session: SessionDep, settings: SettingsDep, limit: int = 30
) -> dict:
    """Р§С‚Рѕ РґРµР»Р°Р» РјР°СЃС‚РµСЂ РїРѕ С…РѕРґР°Рј: РІС‹Р·РѕРІС‹, Р±СЂРѕСЃРєРё, СЂРµР·СѓР»СЊС‚Р°С‚С‹, РѕР±СЂР°С‰РµРЅРёСЏ Рє РјРѕРґРµР»Рё. РўРѕР»СЊРєРѕ Admin Рё Super Admin."""
    await _viewer(session, user, campaign_id)
    if not svc.is_admin(user):
        raise AccessDenied("Р¶СѓСЂРЅР°Р» РјР°СЃС‚РµСЂР° РґРѕСЃС‚СѓРїРµРЅ С‚РѕР»СЊРєРѕ Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂР°Рј")
    return await master_log.build(session, campaign_id, settings, max(1, min(limit, 100)))


# --- РњРµСЃС‚Р° Рё СѓС‡Р°СЃС‚РЅРёРєРё ---


@router.delete("/campaigns/{campaign_id}/seats/{seat_id}/occupant")
async def kick(campaign_id: str, seat_id: str, user: UserDep, session: SessionDep, request: Request) -> CampaignOut:
    v = await _viewer(session, user, campaign_id)
    await svc.free_seat(session, v, seat_id)
    await session.commit()
    await request.app.state.bus.publish(campaign_id, envelope("seat.changed", campaign_id, {"seat_id": seat_id}), None)
    return await campaign_out(session, v.campaign, user)


class SeatAgentIn(BaseModel):
    model_profile_id: str | None = None


@router.post("/campaigns/{campaign_id}/seats/{seat_id}/agent")
async def seat_agent(
    campaign_id: str, seat_id: str, body: SeatAgentIn, user: UserDep, session: SessionDep, request: Request
) -> CampaignOut:
    """РР-РёРіСЂРѕРє РЅР° РїСѓСЃС‚РѕРµ РјРµСЃС‚Рѕ (СЌС‚Р°Рї 9). Р“РµСЂРѕСЏ РµРјСѓ РІР»Р°РґРµР»РµС† СЃРѕР±РёСЂР°РµС‚ СЃР°Рј: РєРѕРЅСЃС‚СЂСѓРєС‚РѕСЂ СЃ ``as_seat``."""
    v = await _viewer(session, user, campaign_id)
    await svc.seat_agent(session, v, seat_id, body.model_profile_id)
    await session.commit()
    await request.app.state.bus.publish(campaign_id, envelope("seat.changed", campaign_id, {"seat_id": seat_id}), None)
    return await campaign_out(session, v.campaign, user)


@router.get("/campaigns/{campaign_id}/party-roles")
async def get_party_roles(campaign_id: str, user: UserDep, session: SessionDep) -> dict:
    """РљР°РєРёС… СЂРѕР»РµР№ РЅРµ С…РІР°С‚Р°РµС‚ РѕС‚СЂСЏРґСѓ Рё РєР°РєРёРµ РєР»Р°СЃСЃС‹ РёС… Р·Р°РєСЂРѕСЋС‚ вЂ” РїРѕРґСЃРєР°Р·РєР° РїРµСЂРµРґ С‚РµРј, РєР°Рє СЃР°Р¶Р°С‚СЊ РР-РёРіСЂРѕРєР°."""
    from app.content.catalog import campaign_catalog
    from app.core.party import party_roles

    v = await _viewer(session, user, campaign_id)
    return await party_roles(session, v.campaign, await campaign_catalog(session, v.campaign))


@router.post("/campaigns/{campaign_id}/seats/take")
async def take_seat(campaign_id: str, user: UserDep, session: SessionDep, request: Request) -> CampaignOut:
    v = await _viewer(session, user, campaign_id)
    seat = await svc.take_seat(session, v)
    await session.commit()
    await request.app.state.bus.publish(campaign_id, envelope("seat.changed", campaign_id, {"seat_id": seat.id}), None)
    return await campaign_out(session, v.campaign, user)


@router.post("/campaigns/{campaign_id}/leave", status_code=204)
async def leave(campaign_id: str, user: UserDep, session: SessionDep, request: Request) -> Response:
    v = await _viewer(session, user, campaign_id)
    seat_id = v.seat.id if v.seat else None
    await svc.leave_campaign(session, v)
    await session.commit()
    await request.app.state.bus.publish(campaign_id, envelope("seat.changed", campaign_id, {"seat_id": seat_id}), None)
    return Response(status_code=204)


# --- РџСЂРёРіР»Р°С€РµРЅРёСЏ ---


@router.post("/campaigns/{campaign_id}/invites", status_code=201)
async def create_invite(
    campaign_id: str, body: InviteCreateIn, user: UserDep, session: SessionDep, settings: SettingsDep
) -> InviteOut:
    v = await _viewer(session, user, campaign_id)
    expires = datetime.now(UTC) + timedelta(hours=body.expires_in_hours) if body.expires_in_hours else None
    invite = await svc.create_invite(session, v, expires_at=expires, max_uses=body.max_uses)
    await session.commit()
    return invite_out(invite, settings.public_url)


@router.get("/campaigns/{campaign_id}/invites")
async def list_invites(campaign_id: str, user: UserDep, session: SessionDep, settings: SettingsDep) -> list[InviteOut]:
    v = await _viewer(session, user, campaign_id)
    if not v.can_manage_members:
        raise AccessDenied("С‚РѕР»СЊРєРѕ РІР»Р°РґРµР»РµС†")
    rows = (await session.scalars(select(Invite).where(Invite.campaign_id == campaign_id))).all()
    return [invite_out(i, settings.public_url) for i in rows]


@router.delete("/campaigns/{campaign_id}/invites/{token}", status_code=204)
async def revoke_invite(campaign_id: str, token: str, user: UserDep, session: SessionDep) -> Response:
    v = await _viewer(session, user, campaign_id)
    if not v.can_manage_members:
        raise AccessDenied("С‚РѕР»СЊРєРѕ РІР»Р°РґРµР»РµС†")
    invite = await session.get(Invite, token)
    if invite is None or invite.campaign_id != campaign_id:
        raise NotFound("РїСЂРёРіР»Р°С€РµРЅРёРµ РЅРµ РЅР°Р№РґРµРЅРѕ")
    invite.revoked = True
    await session.commit()
    return Response(status_code=204)


@router.get("/invites/{token}")
async def preview_invite(token: str, session: SessionDep) -> InvitePreviewOut:
    """Р‘РµР· РІС…РѕРґР°: С‡С‚Рѕ Р·Р° РєР°РјРїР°РЅРёСЏ Рё РµСЃС‚СЊ Р»Рё РјРµСЃС‚Р°. РЎРєСЂС‹С‚С‹С… РґР°РЅРЅС‹С… Р·РґРµСЃСЊ РЅРµС‚."""
    invite = await session.get(Invite, token)
    problem = svc.invite_problem(invite)
    campaign = await session.get(Campaign, invite.campaign_id) if invite else None
    if campaign is None:
        return InvitePreviewOut(campaign_name="", public_intro="", free_seats=0, valid=False, problem=problem)
    free = sum(1 for s in campaign.seats if s.role == "player" and s.occupant_type == "empty")
    return InvitePreviewOut(
        campaign_name=campaign.name,
        public_intro=campaign.public_intro,
        free_seats=free,
        valid=problem is None and free > 0,
        problem=problem or (None if free else "СЃРІРѕР±РѕРґРЅС‹С… РјРµСЃС‚ РЅРµС‚"),
        pack_id=campaign.pack_id,
    )


@router.post("/invites/{token}/accept")
async def accept(token: str, user: UserDep, session: SessionDep, request: Request) -> CampaignOut:
    seat = await svc.accept_invite(session, user, token)
    await session.commit()
    campaign = await session.get(Campaign, seat.campaign_id)
    await request.app.state.bus.publish(campaign.id, envelope("seat.changed", campaign.id, {"seat_id": seat.id}), None)
    return await campaign_out(session, campaign, user)


# --- РЎРµСЃСЃРёРё ---


@router.post("/campaigns/{campaign_id}/session/{action}")
async def control_session(
    campaign_id: str, action: str, user: UserDep, session: SessionDep, request: Request
) -> CampaignOut:
    v = await _viewer(session, user, campaign_id)
    recap = None
    if action == "start":
        game, msg = await chat.start_session(session, v)
        event = "session.started"
        last = await memory.latest(session, campaign_id)
        if last is not None and last.content.get("recap"):
            # РјР°СЃС‚РµСЂ РѕС‚РєСЂС‹РІР°РµС‚ СЃРµСЃСЃРёСЋ РєРѕСЂРѕС‚РєРёРј В«Р Р°РЅРµРµ РІ РєР°РјРїР°РЅРёРёвЂ¦В» РїРѕ СЃРІРѕРґРєРµ (СЂР°Р·РґРµР» 5)
            recap = await chat.system_message(session, v.campaign, "Р Р°РЅРµРµ РІ РєР°РјРїР°РЅРёРё: " + last.content["recap"], game)
    elif action in ("pause", "end"):
        game, msg = await chat.stop_session(session, v, "paused" if action == "pause" else "ended")
        event = "session.paused" if action == "pause" else "session.ended"
    else:
        raise NotFound("РґРµР№СЃС‚РІРёРµ: start, pause РёР»Рё end")
    game_id = game.id if game else None
    await session.commit()
    bus = request.app.state.bus
    await publish_message(bus, msg)
    if recap is not None:
        await publish_message(bus, recap)
    await bus.publish(campaign_id, envelope(event, campaign_id, {"status": v.campaign.status}), None)
    if action in ("pause", "end"):
        await request.app.state.presence.session_stopped(campaign_id)  # Р·Р°РјРµС‰РµРЅРёСЏ Рё РіРѕР»РѕСЃРѕРІР°РЅРёСЏ Р·Р°РєР°РЅС‡РёРІР°СЋС‚СЃСЏ
        # СЃРІРѕРґРєР° СЃРµСЃСЃРёРё, Р·Р°С‚РµРј Сѓ РР-РјР°СЃС‚РµСЂР° СЃ РєР°СЂРєР°СЃРѕРј Р·Р°С†РµРїРєР° РЅР° СЃР»РµРґСѓСЋС‰РёР№ СЂР°Р· РёР»Рё, РїСЂРё Р·Р°РІРµСЂС€РµРЅРёРё, СЌРїРёР»РѕРі
        request.app.state.master.schedule_session_close(campaign_id, game_id, ended=action == "end")
    else:
        request.app.state.master.schedule_session_open(campaign_id, game_id)  # РІСЃС‚СѓРїР»РµРЅРёРµ Рё С†РµР»СЊ РЅР° РІРµС‡РµСЂ
    return await campaign_out(session, v.campaign, user)

