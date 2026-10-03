"""Профиль: у всех — аккаунт и статистика; у Super Admin — ещё роли пользователей.
Настройка моделей ИИ для Admin и Super Admin — в app/api/models.py."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import delete, func, select

from app.api.auth import user_out
from app.api.deps import SessionDep, UserDep
from app.api.schemas import MePatchIn, PasswordIn, ProfileOut, UserOut, UserRoleIn
from app.core.campaigns import AccessDenied, Conflict, NotFound, is_admin
from app.core.security import hash_password, verify_password
from app.db.models import Campaign, Invite, LibraryCharacter, LlmCall, Seat, User

router = APIRouter(prefix="/api", tags=["profile"])


async def _count(session, q) -> int:
    return int(await session.scalar(q) or 0)


@router.get("/me/profile")
async def profile(user: UserDep, session: SessionDep) -> ProfileOut:
    stats = {
        "campaigns_owned": await _count(
            session, select(func.count()).select_from(Campaign).where(Campaign.owner_id == user.id)
        ),
        "campaigns_playing": await _count(
            session,
            select(func.count(func.distinct(Seat.campaign_id))).where(Seat.user_id == user.id, Seat.role == "player"),
        ),
        "campaigns_mastering": await _count(
            session,
            select(func.count(func.distinct(Seat.campaign_id))).where(Seat.user_id == user.id, Seat.role == "master"),
        ),
        "library_characters": await _count(
            session, select(func.count()).select_from(LibraryCharacter).where(LibraryCharacter.owner_user_id == user.id)
        ),
    }
    if is_admin(user):
        owned = select(Campaign.id).where(Campaign.owner_id == user.id)
        row = (
            await session.execute(
                select(func.count(), func.coalesce(func.sum(LlmCall.cost), 0.0)).where(LlmCall.campaign_id.in_(owned))
            )
        ).one()
        stats["llm_calls"], stats["llm_spend_usd"] = int(row[0]), round(float(row[1]), 4)
    return ProfileOut(
        user=user_out(user),
        created_at=user.created_at,
        stats=stats,
        can_manage_models=is_admin(user),
        can_manage_users=user.platform_role == "super_admin",
    )


@router.patch("/me")
async def rename(body: MePatchIn, user: UserDep, session: SessionDep) -> UserOut:
    taken = (await session.scalars(select(User).where(User.name == body.name, User.id != user.id))).first()
    if taken is not None:
        raise Conflict("имя занято")
    user.name = body.name
    await session.commit()
    return user_out(user)


@router.post("/me/password", status_code=204)
async def change_password(body: PasswordIn, user: UserDep, session: SessionDep) -> None:
    if not verify_password(body.old_password, user.password_hash):
        raise Conflict("текущий пароль указан неверно")
    user.password_hash = hash_password(body.new_password)
    await session.commit()


@router.patch("/admin/users/{user_id}")
async def set_role(user_id: str, body: UserRoleIn, user: UserDep, session: SessionDep) -> UserOut:
    """Super Admin меняет роль пользователя. Себя понизить нельзя, чтобы платформа не осталась без Super Admin."""
    if user.platform_role != "super_admin":
        raise AccessDenied("только Super Admin")
    target = await session.get(User, user_id)
    if target is None:
        raise NotFound("пользователь не найден")
    if target.id == user.id and body.platform_role != "super_admin":
        raise Conflict("свою роль Super Admin снять нельзя")
    target.platform_role = body.platform_role
    await session.commit()
    return user_out(target)


@router.delete("/admin/users/{user_id}", status_code=204)
async def delete_user(user_id: str, user: UserDep, session: SessionDep) -> None:
    """Super Admin удаляет учётную запись, не оставляя её в местах кампаний и приглашениях."""
    if user.platform_role != "super_admin":
        raise AccessDenied("только Super Admin")
    target = await session.get(User, user_id)
    if target is None:
        raise NotFound("пользователь не найден")
    if target.id == user.id:
        raise Conflict("нельзя удалить собственную учётную запись")
    if await session.scalar(select(Campaign.id).where(Campaign.owner_id == target.id).limit(1)) is not None:
        raise Conflict("сначала передайте или удалите кампании пользователя")

    seats = (await session.scalars(select(Seat).where(Seat.user_id == target.id))).all()
    if any(seat.role == "master" for seat in seats):
        raise Conflict("сначала замените мастера во всех кампаниях пользователя")
    for seat in seats:
        seat.occupant_type, seat.user_id, seat.joined_at = "empty", None, None
        seat.delegated_from = seat.stand_in_user_id = None

    # У Invite.created_by нет SET NULL: приглашения удалённого пользователя больше не должны работать.
    await session.execute(delete(Invite).where(Invite.created_by == target.id))
    await session.delete(target)
    await session.commit()
