"""Модели ИИ в админке: провайдеры, профили моделей, проверка связи (Admin и Super Admin).

Профиль по умолчанию назначает только Super Admin: его получает мастер новой кампании, если модель не выбрана.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select, update

from app.agents.llm import LLMError, model_for
from app.agents.providers import check_model, list_local_models, provider_status
from app.api.deps import SessionDep, UserDep
from app.api.schemas import ModelCheckIn, ModelProfileIn, ModelProfileOut, ModelProfilePatchIn, ProviderOut
from app.core.campaigns import AccessDenied, Conflict, NotFound, is_admin
from app.db.models import AgentConfig, ModelProfile, User

router = APIRouter(prefix="/api/admin", tags=["models"])


def require_admin(user: User) -> None:
    if not is_admin(user):
        raise AccessDenied("настройка моделей доступна Admin и Super Admin")


def resolved(provider: str, model: str) -> str | None:
    try:
        return model_for(provider, model)
    except LLMError:
        return None


async def profile_out(session, p: ModelProfile) -> ModelProfileOut:
    author = await session.get(User, p.created_by) if p.created_by else None
    linked = AgentConfig.settings["model_profile_id"].as_string() == p.id
    used = await session.scalar(select(func.count()).select_from(AgentConfig).where(linked))
    return ModelProfileOut(
        id=p.id,
        name=p.name,
        provider=p.provider,
        model=p.model,
        resolved_model=resolved(p.provider, p.model),
        api_base=p.api_base,
        temperature=p.temperature,
        is_default=p.is_default,
        created_by_name=author.name if author else None,
        last_check=p.last_check or {},
        campaigns=int(used or 0),
        updated_at=p.updated_at,
    )


def validate(provider: str, model: str) -> None:
    if provider != "claude" and not model.strip():
        raise Conflict("для этого провайдера укажите модель: имя модели, как оно записано у провайдера")


async def set_default(session, user: User, p: ModelProfile, value: bool) -> None:
    if user.platform_role != "super_admin":
        raise AccessDenied("модель по умолчанию назначает только Super Admin")
    if value:
        await session.execute(update(ModelProfile).where(ModelProfile.id != p.id).values(is_default=False))
    p.is_default = value


async def get_profile(session, profile_id: str) -> ModelProfile:
    p = await session.get(ModelProfile, profile_id)
    if p is None:
        raise NotFound("профиль модели не найден")
    return p


async def name_taken(session, name: str, except_id: str | None = None) -> bool:
    q = select(ModelProfile).where(ModelProfile.name == name)
    if except_id:
        q = q.where(ModelProfile.id != except_id)
    return (await session.scalars(q)).first() is not None


@router.get("/providers")
async def providers(user: UserDep) -> list[ProviderOut]:
    """Провайдеры и задан ли на сервере ключ. Сами ключи не отдаются."""
    require_admin(user)
    return [ProviderOut(**p) for p in provider_status()]


@router.get("/providers/local/models")
async def local_models(user: UserDep, api_base: str | None = None) -> list[str]:
    require_admin(user)
    try:
        return await list_local_models(api_base)
    except LLMError as e:
        raise Conflict(str(e)) from e


@router.post("/models/check")
async def check_unsaved(body: ModelCheckIn, user: UserDep, request: Request) -> dict:
    require_admin(user)
    return await check_model(request.app.state.master.llm, body.provider, body.model, body.api_base)


@router.get("/models")
async def list_profiles(user: UserDep, session: SessionDep) -> list[ModelProfileOut]:
    require_admin(user)
    q = select(ModelProfile).order_by(ModelProfile.is_default.desc(), ModelProfile.name)
    rows = (await session.scalars(q)).all()
    return [await profile_out(session, p) for p in rows]


@router.post("/models", status_code=201)
async def create_profile(body: ModelProfileIn, user: UserDep, session: SessionDep) -> ModelProfileOut:
    require_admin(user)
    validate(body.provider, body.model)
    if await name_taken(session, body.name):
        raise Conflict("профиль с таким названием уже есть")
    p = ModelProfile(
        name=body.name,
        provider=body.provider,
        model=body.model.strip(),
        api_base=body.api_base if body.provider == "local" else None,
        temperature=body.temperature,
        created_by=user.id,
        last_check={},
    )
    session.add(p)
    await session.flush()
    if body.is_default:
        await set_default(session, user, p, True)
    await session.commit()
    return await profile_out(session, p)


@router.patch("/models/{profile_id}")
async def patch_profile(
    profile_id: str, body: ModelProfilePatchIn, user: UserDep, session: SessionDep
) -> ModelProfileOut:
    require_admin(user)
    p = await get_profile(session, profile_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and await name_taken(session, data["name"], p.id):
        raise Conflict("профиль с таким названием уже есть")
    changed_model = any(k in data for k in ("provider", "model", "api_base"))
    for k in ("name", "provider", "temperature"):
        if data.get(k) is not None:
            setattr(p, k, data[k])
    if data.get("model") is not None:
        p.model = data["model"].strip()
    if "api_base" in data:
        p.api_base = data["api_base"]
    if p.provider != "local":
        p.api_base = None
    validate(p.provider, p.model)
    if "is_default" in data and data["is_default"] is not None:
        await set_default(session, user, p, data["is_default"])
    if changed_model:
        p.last_check = {}  # прежняя проверка относилась к другой модели
    await session.commit()
    return await profile_out(session, p)


@router.delete("/models/{profile_id}", status_code=204)
async def delete_profile(profile_id: str, user: UserDep, session: SessionDep) -> Response:
    """Кампании хранят копию настроек, поэтому удаление профиля их не останавливает."""
    require_admin(user)
    p = await get_profile(session, profile_id)
    if p.is_default and user.platform_role != "super_admin":
        raise AccessDenied("модель по умолчанию удаляет только Super Admin")
    await session.delete(p)
    await session.commit()
    return Response(status_code=204)


@router.post("/models/{profile_id}/check")
async def check_profile(profile_id: str, user: UserDep, session: SessionDep, request: Request) -> ModelProfileOut:
    require_admin(user)
    p = await get_profile(session, profile_id)
    provider, model, api_base = p.provider, p.model, p.api_base
    await session.rollback()  # не держим транзакцию, пока модель отвечает: это может длиться до минуты
    result = await check_model(request.app.state.master.llm, provider, model, api_base)
    p = await get_profile(session, profile_id)
    p.last_check = result
    await session.commit()
    return await profile_out(session, p)
