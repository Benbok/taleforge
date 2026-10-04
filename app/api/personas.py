"""Персоны ИИ-мастера в профиле Admin и варианты анкеты кампании (проект «Подготовка кампании»)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.agents import character
from app.agents.llm import model_for
from app.api.deps import SessionDep, UserDep
from app.api.schemas import (
    MasterPersonaIn,
    MasterPersonaOut,
    MasterPersonaPatchIn,
    MasterPresetIn,
    MasterPresetOut,
    MasterPresetPatchIn,
)
from app.core import brief, persona, personas
from app.core.campaigns import AccessDenied, Conflict, NotFound, is_admin
from app.db.models import MasterPersona, MasterPreset, ModelProfile, User

router = APIRouter(prefix="/api", tags=["personas"])


def require_admin(user: User) -> None:
    if not is_admin(user):
        raise AccessDenied("персоны мастера доступны Admin и Super Admin")


def out(p: MasterPersona) -> MasterPersonaOut:
    return MasterPersonaOut(
        id=p.id, name=p.name, settings=p.settings, style=personas.compose_style(p.settings), updated_at=p.updated_at
    )


async def mine(session, user: User, persona_id: str) -> MasterPersona:
    p = await session.get(MasterPersona, persona_id)
    if p is None or p.user_id != user.id:
        raise NotFound("персона мастера не найдена")
    return p


async def name_taken(session, user: User, name: str, except_id: str | None = None) -> bool:
    q = select(MasterPersona.id).where(MasterPersona.user_id == user.id, MasterPersona.name == name)
    if except_id:
        q = q.where(MasterPersona.id != except_id)
    return (await session.scalars(q)).first() is not None


@router.get("/campaign-options")
async def campaign_options(user: UserDep) -> dict:
    """Варианты анкеты кампании и настроек персоны мастера с русскими подписями, встроенные персоны."""
    presets = [{**p, "style": personas.compose_style(p["settings"])} for p in personas.PRESETS]
    return {"brief": brief.options(), "persona": personas.options(), "presets": presets}


@router.get("/me/master-personas")
async def list_personas(user: UserDep, session: SessionDep) -> list[MasterPersonaOut]:
    require_admin(user)
    q = select(MasterPersona).where(MasterPersona.user_id == user.id).order_by(MasterPersona.name)
    return [out(p) for p in (await session.scalars(q)).all()]


@router.post("/me/master-personas", status_code=201)
async def create_persona(body: MasterPersonaIn, user: UserDep, session: SessionDep) -> MasterPersonaOut:
    require_admin(user)
    name = body.name.strip()
    if await name_taken(session, user, name):
        raise Conflict("персона с таким названием уже есть")
    p = MasterPersona(user_id=user.id, name=name, settings=body.settings.model_dump())
    session.add(p)
    await session.commit()
    return out(p)


@router.patch("/me/master-personas/{persona_id}")
async def patch_persona(
    persona_id: str, body: MasterPersonaPatchIn, user: UserDep, session: SessionDep
) -> MasterPersonaOut:
    """Правка персоны в профиле не меняет кампании: у них своя копия."""
    require_admin(user)
    p = await mine(session, user, persona_id)
    if body.name is not None:
        name = body.name.strip()
        if await name_taken(session, user, name, p.id):
            raise Conflict("персона с таким названием уже есть")
        p.name = name
    if body.settings is not None:
        p.settings = body.settings.model_dump()
    await session.commit()
    return out(p)


@router.delete("/me/master-personas/{persona_id}", status_code=204)
async def delete_persona(persona_id: str, user: UserDep, session: SessionDep) -> Response:
    require_admin(user)
    await session.delete(await mine(session, user, persona_id))
    await session.commit()
    return Response(status_code=204)


# --- Пресеты ИИ-мастера (модель + стиль + анкета характера) ---


async def preset_out(session, p: MasterPreset) -> MasterPresetOut:
    profile = await session.get(ModelProfile, p.model_profile_id) if p.model_profile_id else None
    resolved = None
    if profile:
        try:
            resolved = model_for(profile.provider, profile.model)
        except Exception:
            resolved = None

    style_preview = None
    if p.persona_settings:
        style_preview = personas.compose_style(p.persona_settings, p.style)
    elif p.style:
        style_preview = p.style

    char_dict = persona.normalize(p.character, master=True) if p.character else None

    return MasterPresetOut(
        id=p.id,
        name=p.name,
        model_profile_id=p.model_profile_id,
        model_profile_name=profile.name if profile else None,
        model_resolved=resolved,
        provider=profile.provider if profile else None,
        persona_id=p.persona_id,
        persona_preset=p.persona_preset,
        persona_settings=p.persona_settings,
        style=p.style,
        style_preview=style_preview,
        character=char_dict,
        updated_at=p.updated_at,
    )


async def mine_preset(session, user: User, preset_id: str) -> MasterPreset:
    p = await session.get(MasterPreset, preset_id)
    if p is None or p.user_id != user.id:
        raise NotFound("пресет мастера не найден")
    return p


async def preset_name_taken(session, user: User, name: str, except_id: str | None = None) -> bool:
    q = select(MasterPreset.id).where(MasterPreset.user_id == user.id, MasterPreset.name == name)
    if except_id:
        q = q.where(MasterPreset.id != except_id)
    return (await session.scalars(q)).first() is not None


@router.get("/me/master-presets")
async def list_presets(user: UserDep, session: SessionDep) -> list[MasterPresetOut]:
    require_admin(user)
    q = select(MasterPreset).where(MasterPreset.user_id == user.id).order_by(MasterPreset.name)
    presets = (await session.scalars(q)).all()
    return [await preset_out(session, p) for p in presets]


@router.post("/me/master-presets", status_code=201)
async def create_preset(body: MasterPresetIn, user: UserDep, session: SessionDep) -> MasterPresetOut:
    require_admin(user)
    name = body.name.strip()
    if await preset_name_taken(session, user, name):
        raise Conflict("пресет с таким названием уже есть")
    char_dict = persona.normalize(body.character.model_dump() if body.character else {}, master=True)
    settings_dict = body.persona_settings.model_dump() if body.persona_settings else {}
    p = MasterPreset(
        user_id=user.id,
        name=name,
        model_profile_id=body.model_profile_id,
        persona_id=body.persona_id,
        persona_preset=body.persona_preset,
        persona_settings=settings_dict,
        style=body.style,
        character=char_dict,
    )
    session.add(p)
    await session.commit()
    return await preset_out(session, p)


@router.get("/me/master-presets/{preset_id}")
async def get_preset(preset_id: str, user: UserDep, session: SessionDep) -> MasterPresetOut:
    require_admin(user)
    return await preset_out(session, await mine_preset(session, user, preset_id))


@router.patch("/me/master-presets/{preset_id}")
async def patch_preset(
    preset_id: str, body: MasterPresetPatchIn, user: UserDep, session: SessionDep
) -> MasterPresetOut:
    require_admin(user)
    p = await mine_preset(session, user, preset_id)
    if body.name is not None:
        name = body.name.strip()
        if await preset_name_taken(session, user, name, p.id):
            raise Conflict("пресет с таким названием уже есть")
        p.name = name
    if body.model_profile_id is not None:
        p.model_profile_id = body.model_profile_id or None
    if body.persona_id is not None:
        p.persona_id = body.persona_id or None
    if body.persona_preset is not None:
        p.persona_preset = body.persona_preset or None
    if body.persona_settings is not None:
        p.persona_settings = body.persona_settings.model_dump()
    if body.style is not None:
        p.style = body.style
    if body.character is not None:
        p.character = persona.normalize(body.character.model_dump(), master=True)
    await session.commit()
    return await preset_out(session, p)


@router.delete("/me/master-presets/{preset_id}", status_code=204)
async def delete_preset(preset_id: str, user: UserDep, session: SessionDep) -> Response:
    require_admin(user)
    await session.delete(await mine_preset(session, user, preset_id))
    await session.commit()
    return Response(status_code=204)


@router.post("/me/master-presets/test")
async def test_preset(body: dict, user: UserDep, request: Request) -> dict:
    """Генерирует три пробные сцены для проверки характера пресета мастера."""
    require_admin(user)
    sheet = body.get("character") or body.get("persona") or {}
    profile_id = body.get("model_profile_id")
    style = body.get("style")
    scenes = await character.try_preset_scenes(request.app.state.master, profile_id, sheet, style=style)
    return {"scenes": scenes}
