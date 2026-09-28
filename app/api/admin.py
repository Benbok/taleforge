from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.auth import user_out
from app.api.deps import SessionDep, UserDep
from app.api.schemas import PackOut, UserCreateIn, UserOut
from app.core.campaigns import DEFAULT_PARTY, AccessDenied, Conflict, is_admin
from app.core.security import hash_password
from app.db.models import ContentPack, User

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


@router.get("/packs")
async def list_packs(user: UserDep, session: SessionDep) -> list[PackOut]:
    """Пакеты для мастера создания кампании. Импорт — командой `python -m app.content import`."""
    if not is_admin(user):
        raise AccessDenied("только Admin")
    rows = (await session.scalars(select(ContentPack).order_by(ContentPack.id, ContentPack.imported_at))).all()
    return [
        PackOut(
            id=p.id,
            version=p.version,
            name=p.name,
            party_size={**DEFAULT_PARTY, **(p.manifest.get("party_size") or {})},
            counts=(p.import_report or {}).get("counts", {}),
            imported_at=p.imported_at,
        )
        for p in rows
    ]
