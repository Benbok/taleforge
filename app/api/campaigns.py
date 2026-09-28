from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.api.deps import SessionDep, SettingsDep, UserDep
from app.api.schemas import (
    CampaignCreateIn,
    CampaignOut,
    CampaignPatchIn,
    InviteCreateIn,
    InviteOut,
    InvitePreviewOut,
    SeatOut,
    SecretsIn,
)
from app.content.catalog import CatalogError, resolve_chain
from app.content.importer import latest_version
from app.core import campaigns as svc
from app.core import chat
from app.core.campaigns import AccessDenied, Conflict, NotFound, Viewer
from app.db.models import AgentConfig, Campaign, CampaignSecret, ContentPack, Invite, User
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
async def patch_campaign(campaign_id: str, body: CampaignPatchIn, user: UserDep, session: SessionDep) -> CampaignOut:
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
    for key in ("turn_timeout_sec", "spend_limit_usd", "collect_window_sec", "excluded_themes"):
        if key in body.model_fields_set:
            settings[key] = getattr(body, key)
    c.settings = settings
    await session.commit()
    return await campaign_out(session, c, user)


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


# --- Места и участники ---


@router.delete("/campaigns/{campaign_id}/seats/{seat_id}/occupant")
async def kick(campaign_id: str, seat_id: str, user: UserDep, session: SessionDep, request: Request) -> CampaignOut:
    v = await _viewer(session, user, campaign_id)
    await svc.free_seat(session, v, seat_id)
    await session.commit()
    await request.app.state.bus.publish(campaign_id, envelope("seat.changed", campaign_id, {"seat_id": seat_id}), None)
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
    if action == "start":
        _, msg = await chat.start_session(session, v)
        event = "session.started"
    elif action in ("pause", "end"):
        _, msg = await chat.stop_session(session, v, "paused" if action == "pause" else "ended")
        event = "session.paused" if action == "pause" else "session.ended"
    else:
        raise NotFound("действие: start, pause или end")
    await session.commit()
    bus = request.app.state.bus
    await publish_message(bus, msg)
    await bus.publish(campaign_id, envelope(event, campaign_id, {"status": v.campaign.status}), None)
    return await campaign_out(session, v.campaign, user)
