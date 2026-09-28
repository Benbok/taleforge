from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import SessionDep, SettingsDep, UserDep
from app.api.schemas import LoginIn, RegisterByInviteIn, TokenOut, UserOut
from app.core.campaigns import Conflict, accept_invite, invite_problem
from app.core.security import create_token, hash_password, verify_password
from app.db.models import Invite, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, name=u.name, platform_role=u.platform_role)


@router.post("/login")
async def login(body: LoginIn, session: SessionDep, settings: SettingsDep) -> TokenOut:
    user = (await session.scalars(select(User).where(User.name == body.name))).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "неверное имя или пароль")
    return TokenOut(token=create_token(user.id, settings.jwt_secret, settings.jwt_ttl_hours), user=user_out(user))


@router.post("/register/{token}")
async def register_by_invite(
    token: str, body: RegisterByInviteIn, session: SessionDep, settings: SettingsDep
) -> TokenOut:
    """Вход по ссылке без сложной регистрации: имя и пароль, место в кампании занимается сразу."""
    problem = invite_problem(await session.get(Invite, token))
    if problem:
        raise Conflict(problem)
    if (await session.scalars(select(User).where(User.name == body.name))).first() is not None:
        raise Conflict("имя занято: войдите под ним и примите приглашение")
    user = User(name=body.name, password_hash=hash_password(body.password), platform_role="player")
    session.add(user)
    await session.flush()
    await accept_invite(session, user, token)
    await session.commit()
    return TokenOut(token=create_token(user.id, settings.jwt_secret, settings.jwt_ttl_hours), user=user_out(user))


@router.get("/me")
async def me(user: UserDep) -> UserOut:
    return user_out(user)
