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
    MasterModelIn,
    MasterModelOut,
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
from app.db.models import AgentConfig, Campaign, CampaignSecret, ContentPack, Invite, ModelProfile, User
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


# --- Кампании ---


@router.get("/campaigns")
async def list_campaigns(user: UserDep, session: SessionDep) -> list[CampaignOut]:
    return [await campaign_out(session, c, user) for c in await svc.list_campaigns(session, user)]


@router.get("/party-size")
async def recommend_party(
    user: UserDep, session: SessionDep, difficulty: str = "normal", pack_id: str | None = None
) -> dict:
    """Рекомендация размера отряда для мастера создания кампании (раздел 5.2)."""
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
            raise NotFound("пакет не импортирован")
        if pack.manifest.get("ruleset") != "dnd5e":
            raise Conflict("пакет для другой системы правил")
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
        },
        owner_plays=body.owner_plays,
        brief=body.brief.model_dump(exclude_defaults=True),
    )
    try:
        campaign.content_chain = await resolve_chain(session, pack)
    except CatalogError as e:
        if pack is not None:
            raise Conflict(str(e)) from None
        # без пакета мира цепочка — базовый пакет правил; если он ещё не импортирован, её найдут при первой игре
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
        raise AccessDenied("менять кампанию может только владелец")
    c = v.campaign
    if body.name is not None:
        c.name = body.name
    if body.public_intro is not None:
        c.public_intro = body.public_intro
    if body.difficulty is not None:
        c.difficulty = body.difficulty
    settings = dict(c.settings)
    for key in ("turn_timeout_sec", "spend_limit_usd", "collect_window_sec", "excluded_themes", "audio_enabled"):
        if key in body.model_fields_set:
            settings[key] = getattr(body, key)
    sound = bool(settings.get("audio_enabled")) != bool((c.settings or {}).get("audio_enabled"))
    c.settings = settings
    if body.brief is not None:
        c.brief = body.brief.model_dump(exclude_defaults=True)
    await session.commit()
    if sound:  # звук включили или выключили посреди игры: у игроков он заиграет или смолкнет сразу
        sc = await get_scene(session, c.id)
        env = envelope("audio.state", c.id, {**audio.public_state(c, sc), "cues": []})
        await request.app.state.bus.publish(c.id, env, None)
    return await campaign_out(session, c, user)


async def _master_agent(session, user: User, campaign_id: str, what: str = "модель мастера") -> AgentConfig:
    v = await _viewer(session, user, campaign_id)
    if not v.is_owner:
        raise AccessDenied(f"{what} меняет только владелец кампании")
    seat = next((s for s in v.campaign.seats if s.role == "master"), None)
    agent = await session.get(AgentConfig, seat.agent_config_id) if seat and seat.agent_config_id else None
    if agent is None:
        raise Conflict("мастер этой кампании — человек, а не ИИ")
    return agent


async def master_model_out(session, agent: AgentConfig) -> MasterModelOut:
    extra = agent.settings or {}
    profile = await session.get(ModelProfile, extra["model_profile_id"]) if extra.get("model_profile_id") else None
    try:
        resolved = model_for(agent.provider, agent.model)
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
    """Сменить модель ИИ-мастера: следующий ход мастер сделает уже новой моделью."""
    agent = await _master_agent(session, user, campaign_id)
    if not body.model_profile_id and not body.provider:
        raise Conflict("выберите профиль модели или провайдера")
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
    return persona_out(await _master_agent(session, user, campaign_id, "характер мастера"))


@router.put("/campaigns/{campaign_id}/master-persona")
async def put_master_persona(
    campaign_id: str, body: PersonaChoiceIn, user: UserDep, session: SessionDep
) -> CampaignPersonaOut:
    """Сменить характер ИИ-мастера: следующий ход мастер ведёт уже в новом тоне."""
    agent = await _master_agent(session, user, campaign_id, "характер мастера")
    await svc.apply_persona(session, user, agent, body.model_dump())
    await session.commit()
    return persona_out(agent)


# --- характер ИИ-мастера (этап 9б): анкета, помощник, проверка, летопись ---


class MasterCharacterIn(BaseModel):
    text: str = ""
    fields: dict[str, str] = {}
    core: list[str] | None = None


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
    agent = await _master_agent(session, user, campaign_id, "характер мастера")
    return await _master_character_out(session, campaign_id, agent)


@router.put("/campaigns/{campaign_id}/master-character")
async def put_master_character(campaign_id: str, body: MasterCharacterIn, user: UserDep, session: SessionDep) -> dict:
    """Свободный текст и поля характера ИИ-мастера: в подсказку мастера со следующего хода."""
    from app.core import persona

    agent = await _master_agent(session, user, campaign_id, "характер мастера")
    agent.settings = {**(agent.settings or {}), "character": persona.normalize(body.model_dump(), master=True)}
    await session.commit()
    return await _master_character_out(session, campaign_id, agent)


async def _master_draft(session, user, campaign_id: str, body: MasterDraftIn) -> dict:
    agent = await _master_agent(session, user, campaign_id, "характер мастера")
    sheet = body.persona.model_dump() if body.persona else dict((agent.settings or {}).get("character") or {})
    await session.rollback()  # модель думает долго: базу не держим
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
    """Пробные сцены мастера: описание места, реакция NPC, провал героя."""
    from app.agents import character

    sheet = await _master_draft(session, user, campaign_id, body)
    return {"scenes": await character.try_scenes(request.app.state.master, campaign_id, sheet, character_id=None)}


@router.patch("/campaigns/{campaign_id}/master-character/notes/{note_id}")
async def patch_master_note(
    campaign_id: str, note_id: str, body: MasterNoteIn, user: UserDep, session: SessionDep
) -> dict:
    from app.core import persona
    from app.db.models import PersonaNote

    agent = await _master_agent(session, user, campaign_id, "летопись мастера")
    n = await session.get(PersonaNote, note_id)
    if n is None or n.campaign_id != campaign_id or n.character_id is not None:
        raise Conflict("запись летописи не найдена")
    persona.edit_note(n, body.text, body.cause, body.reverted)
    await session.commit()
    return await _master_character_out(session, campaign_id, agent)


@router.delete("/campaigns/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: str, user: UserDep, session: SessionDep, request: Request) -> Response:
    v = await _viewer(session, user, campaign_id)
    if not v.is_owner:
        raise AccessDenied("удалить кампанию может только владелец")
    await session.delete(v.campaign)
    await session.commit()
    await request.app.state.bus.publish(campaign_id, envelope("campaign.deleted", campaign_id, {}), None)
    return Response(status_code=204)


# --- Скрытые данные мастера ---


@router.get("/campaigns/{campaign_id}/secrets")
async def get_secrets(campaign_id: str, user: UserDep, session: SessionDep) -> dict:
    """Только место мастера. Владелец без места мастера их не видит (раздел 2)."""
    v = await _viewer(session, user, campaign_id)
    if not v.is_master:
        raise NotFound("нет доступа")
    s = await session.get(CampaignSecret, campaign_id)
    return {"setting": s.setting, "plot": s.plot}


@router.put("/campaigns/{campaign_id}/secrets")
async def put_secrets(campaign_id: str, body: SecretsIn, user: UserDep, session: SessionDep) -> dict:
    v = await _viewer(session, user, campaign_id)
    if not v.is_master:
        raise NotFound("нет доступа")
    s = await session.get(CampaignSecret, campaign_id)
    if body.setting is not None:
        s.setting = body.setting
    if body.plot is not None:
        s.plot = body.plot
    await session.commit()
    return {"setting": s.setting, "plot": s.plot}


@router.get("/campaigns/{campaign_id}/master-panel")
async def get_master_panel(campaign_id: str, user: UserDep, session: SessionDep) -> dict:
    """Формы инструментов для живого мастера: схемы, допустимые значения и подписи к id. Только место мастера."""
    from app.content.catalog import campaign_catalog
    from app.core.master_panel import panel
    from app.core.world import load_world

    v = await _viewer(session, user, campaign_id)
    if not v.is_master:
        raise NotFound("нет доступа")
    world = await load_world(session, v.campaign, await campaign_catalog(session, v.campaign))
    return panel(world)


# --- Журнал мастера ---


@router.get("/campaigns/{campaign_id}/master-log")
async def get_master_log(
    campaign_id: str, user: UserDep, session: SessionDep, settings: SettingsDep, limit: int = 30
) -> dict:
    """Что делал мастер по ходам: вызовы, броски, результаты, обращения к модели. Только Admin и Super Admin."""
    await _viewer(session, user, campaign_id)
    if not svc.is_admin(user):
        raise AccessDenied("журнал мастера доступен только администраторам")
    return await master_log.build(session, campaign_id, settings, max(1, min(limit, 100)))


# --- Места и участники ---


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
    """ИИ-игрок на пустое место (этап 9). Героя ему владелец собирает сам: конструктор с ``as_seat``."""
    v = await _viewer(session, user, campaign_id)
    await svc.seat_agent(session, v, seat_id, body.model_profile_id)
    await session.commit()
    await request.app.state.bus.publish(campaign_id, envelope("seat.changed", campaign_id, {"seat_id": seat_id}), None)
    return await campaign_out(session, v.campaign, user)


@router.get("/campaigns/{campaign_id}/party-roles")
async def get_party_roles(campaign_id: str, user: UserDep, session: SessionDep) -> dict:
    """Каких ролей не хватает отряду и какие классы их закроют — подсказка перед тем, как сажать ИИ-игрока."""
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


# --- Приглашения ---


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
        raise AccessDenied("только владелец")
    rows = (await session.scalars(select(Invite).where(Invite.campaign_id == campaign_id))).all()
    return [invite_out(i, settings.public_url) for i in rows]


@router.delete("/campaigns/{campaign_id}/invites/{token}", status_code=204)
async def revoke_invite(campaign_id: str, token: str, user: UserDep, session: SessionDep) -> Response:
    v = await _viewer(session, user, campaign_id)
    if not v.can_manage_members:
        raise AccessDenied("только владелец")
    invite = await session.get(Invite, token)
    if invite is None or invite.campaign_id != campaign_id:
        raise NotFound("приглашение не найдено")
    invite.revoked = True
    await session.commit()
    return Response(status_code=204)


@router.get("/invites/{token}")
async def preview_invite(token: str, session: SessionDep) -> InvitePreviewOut:
    """Без входа: что за кампания и есть ли места. Скрытых данных здесь нет."""
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
        problem=problem or (None if free else "свободных мест нет"),
    )


@router.post("/invites/{token}/accept")
async def accept(token: str, user: UserDep, session: SessionDep, request: Request) -> CampaignOut:
    seat = await svc.accept_invite(session, user, token)
    await session.commit()
    campaign = await session.get(Campaign, seat.campaign_id)
    await request.app.state.bus.publish(campaign.id, envelope("seat.changed", campaign.id, {"seat_id": seat.id}), None)
    return await campaign_out(session, campaign, user)


# --- Сессии ---


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
            # мастер открывает сессию коротким «Ранее в кампании…» по сводке (раздел 5)
            recap = await chat.system_message(session, v.campaign, "Ранее в кампании: " + last.content["recap"], game)
    elif action in ("pause", "end"):
        game, msg = await chat.stop_session(session, v, "paused" if action == "pause" else "ended")
        event = "session.paused" if action == "pause" else "session.ended"
    else:
        raise NotFound("действие: start, pause или end")
    game_id = game.id if game else None
    await session.commit()
    bus = request.app.state.bus
    await publish_message(bus, msg)
    if recap is not None:
        await publish_message(bus, recap)
    await bus.publish(campaign_id, envelope(event, campaign_id, {"status": v.campaign.status}), None)
    if action in ("pause", "end"):
        await request.app.state.presence.session_stopped(campaign_id)  # замещения и голосования заканчиваются
        # сводка сессии, затем у ИИ-мастера с каркасом зацепка на следующий раз или, при завершении, эпилог
        request.app.state.master.schedule_session_close(campaign_id, game_id, ended=action == "end")
    else:
        request.app.state.master.schedule_session_open(campaign_id, game_id)  # вступление и цель на вечер
    return await campaign_out(session, v.campaign, user)
