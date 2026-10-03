"""Модели ИИ в админке: провайдеры, профили моделей, проверка связи (Admin и Super Admin).

Профиль по умолчанию назначает только Super Admin: его получает мастер новой кампании, если модель не выбрана.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select, update

from app.agents.providers import check_model, list_local_models, provider_status
from app.api.deps import UserDep
from app.api.schemas import ProviderOut
from app.core.campaigns import AccessDenied, Conflict, is_admin
from app.db.models import User
from app.config import update_env

router = APIRouter(prefix="/api/admin", tags=["models"])


def require_admin(user: User) -> None:
    if not is_admin(user):
        raise AccessDenied("настройка моделей доступна Admin и Super Admin")


@router.get("/providers")
async def providers(user: UserDep) -> list[ProviderOut]:
    """Провайдеры и задан ли на сервере ключ. Сами ключи не отдаются."""
    require_admin(user)
    return [ProviderOut(**p) for p in provider_status()]

class ProviderActivePatch(BaseModel):
    provider: str

@router.patch("/providers/active")
async def set_active_provider(body: ProviderActivePatch, user: UserDep):
    require_admin(user)
    update_env("LLM_PROVIDER", body.provider)
    return {"ok": True}

class ModelCheckIn(BaseModel):
    provider: str
    model: str | None = None
    api_base: str | None = None

@router.post("/providers/check")
async def check_provider(body: ModelCheckIn, user: UserDep, request: Request) -> dict:
    require_admin(user)
    return await check_model(request.app.state.master.llm, body.provider, body.model, body.api_base)

@router.get("/providers/local/models")
async def local_models(user: UserDep, api_base: str | None = None) -> list[str]:
    require_admin(user)
    try:
        from app.agents.llm import LLMError
        return await list_local_models(api_base)
    except LLMError as e:
        raise Conflict(str(e)) from e
