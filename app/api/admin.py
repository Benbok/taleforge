from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.api.auth import user_out
from app.api.deps import SessionDep, UserDep
from app.api.schemas import PackOut, UserCreateIn, UserOut
from app.content.upload import UploadError, upload
from app.core import spend
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
    # готовые приключения тоже пакеты, но выбираются в своём разделе, а не как мир
    rows = [p for p in rows if (p.manifest or {}).get("kind") != "module"]
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


@router.post("/admin/packs")
async def upload_pack(request: Request, user: UserDep, session: SessionDep, dry_run: bool = False) -> dict:
    """Пакет сеттинга zip-архивом в теле запроса. dry_run — только проверка, без записи в БД."""
    if not is_admin(user):
        raise AccessDenied("только Admin")
    try:
        return await upload(session, await request.body(), dry_run=dry_run)
    except UploadError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/admin/spend")
async def get_spend(user: UserDep, session: SessionDep, days: int = 30) -> dict:
    """Расходы на модели за период. Admin — свои кампании, Super Admin — все."""
    if not is_admin(user):
        raise AccessDenied("только Admin")
    return await spend.report(session, user, max(1, min(days, 365)))
