"""Персоны ИИ-мастера в профиле Admin и варианты анкеты кампании (проект «Подготовка кампании»)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.api.schemas import MasterPersonaIn, MasterPersonaOut, MasterPersonaPatchIn
from app.core import brief, personas
from app.core.campaigns import AccessDenied, Conflict, NotFound, is_admin
from app.db.models import MasterPersona, User

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
