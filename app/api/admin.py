from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.auth import user_out
from app.api.deps import SessionDep, UserDep
from app.api.schemas import UserCreateIn, UserOut
from app.core import spend
from app.core.campaigns import AccessDenied, Conflict, is_admin
from app.core.security import hash_password
from app.db.models import User

router = APIRouter(prefix="/api", tags=["admin"])


@router.post("/admin/users", status_code=201)
async def create_user(body: UserCreateIn, user: UserDep, session: SessionDep) -> UserOut:
    """Super Admin заводит админов (и при желании игроков без приглашения)."""
    if user.platform_role != "super_admin":
        raise AccessDenied("только Super Admin")
    if (await session.scalars(select(User).where(User.name == body.name))).first() is not None:
        raise Conflict("имя занято")
    new = User(name=body.name, password_hash=hash_password(body.password), platform_role=body.platform_role)
    session.add(new)
    await session.commit()
    return user_out(new)


@router.get("/admin/users")
async def list_users(user: UserDep, session: SessionDep) -> list[UserOut]:
    if user.platform_role != "super_admin":
        raise AccessDenied("только Super Admin")
    return [user_out(u) for u in (await session.scalars(select(User).order_by(User.created_at))).all()]


@router.get("/admin/spend")
async def get_spend(user: UserDep, session: SessionDep, days: int = 30) -> dict:
    """Расходы на модели за период. Admin — свои кампании, Super Admin — все."""
    if not is_admin(user):
        raise AccessDenied("только Admin")
    return await spend.report(session, user, max(1, min(days, 365)))
