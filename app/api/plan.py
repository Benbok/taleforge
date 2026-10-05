"""Каркас кампании: статус, афиша, примерная стоимость и (пере)генерация до начала игры.

Содержимое каркаса видит только место мастера (через /secrets); владелец без места мастера видит афишу и завязку.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.agents import architect
from app.api.deps import SessionDep, UserDep
from app.content.catalog import campaign_catalog
from app.core import adventure, plot
from app.core import campaigns as svc
from app.core.campaigns import AccessDenied, Conflict, NotFound
from app.db.models import CampaignPlan, CampaignSecret, User

router = APIRouter(prefix="/api", tags=["plan"])


class PlanRequestIn(BaseModel):
    note: str = Field(default="", max_length=500, description="пожелание к варианту: «мрачнее», «короче»")
    structure_id: str | None = None


async def _manager(session, user: User, campaign_id: str):
    v = await svc.get_viewer(session, user, campaign_id)
    if not (v.is_owner or v.is_master):
        raise AccessDenied("каркас готовит владелец или мастер")
    return v


async def can_generate(session, c) -> bool:
    """Каркас целиком строится до первой сессии. Если игра началась без него (сбой генерации), его можно доделать.
    У готового приключения каркас — из книги, архитектор его не перестраивает."""
    if adventure.is_module(c):
        return False
    if not await architect.started(session, c.id):
        return True
    secret = await session.get(CampaignSecret, c.id)
    return not plot.has_plan(secret.plot if secret else None)


async def plan_out(session, v) -> dict:
    c = v.campaign
    st = c.settings or {}
    versions = await session.scalar(
        select(func.count()).select_from(CampaignPlan).where(CampaignPlan.campaign_id == c.id)
    )
    status, error = plot.status(st)
    out = {
        "status": status,
        "error": error,
        "version": (st.get("plan") or {}).get("version"),
        "versions": int(versions or 0),
        "poster": st.get("poster"),
        "public_intro": c.public_intro,
        "can_generate": await can_generate(session, c),
    }
    if v.is_master:
        secret = await session.get(CampaignSecret, c.id)
        out["plan"] = secret.plot if secret else {}
        out["revision"] = (st.get("plan") or {}).get("revision")
        last = await session.scalar(
            select(CampaignPlan).where(CampaignPlan.campaign_id == c.id).order_by(CampaignPlan.version.desc()).limit(1)
        )
        out["note"] = last.note if last else None
    return out


@router.get("/campaigns/{campaign_id}/plan")
async def get_plan(campaign_id: str, user: UserDep, session: SessionDep) -> dict:
    return await plan_out(session, await _manager(session, user, campaign_id))


@router.get("/campaigns/{campaign_id}/plan/options")
async def plan_options(campaign_id: str, user: UserDep, session: SessionDep, structure_id: str | None = None) -> dict:
    """Шаблоны сюжета (с тем, что подходит под анкету) и примерная стоимость генерации."""
    v = await _manager(session, user, campaign_id)
    c = v.campaign
    catalog = await campaign_catalog(session, c)
    structures = catalog.by_kind("plot_structure")
    best = plot.pick_structure(structures, c.brief or {})
    try:
        prompt, sid = await architect.build_input(session, c, "", structure_id)
    except LookupError as e:
        raise NotFound(str(e)) from None
    _, model, _, _ = await architect.model_of(session, c)
    return {
        "structures": [
            {
                "id": e.id,
                "name": e.name,
                "description": e.data.get("description", ""),
                "best": best is not None and e.id == best.id,
            }
            for e in sorted(structures, key=lambda e: -plot.score_structure(e.data, c.brief or {}))
        ],
        "structure_id": sid,
        "estimate": architect.estimate_cost(model, prompt, architect.length_of(c)),
    }


@router.post("/campaigns/{campaign_id}/plan", status_code=202)
async def request_plan(
    campaign_id: str, body: PlanRequestIn, user: UserDep, session: SessionDep, request: Request
) -> dict:
    """Построить каркас или новый вариант: до первой сессии или пока каркаса нет. Потом он меняется по ходу игры."""
    v = await _manager(session, user, campaign_id)
    c = v.campaign
    if adventure.is_module(c):
        raise Conflict("каркас готового приключения взят из книги и не перестраивается")
    if not await can_generate(session, c):
        raise Conflict("игра уже началась: каркас больше не перегенерируется целиком")
    if plot.status(c.settings)[0] == "generating":
        raise Conflict("каркас уже готовится")
    if body.structure_id:
        catalog = await campaign_catalog(session, c)
        if catalog.find(body.structure_id, "plot_structure") is None:
            raise NotFound("шаблон сюжета не найден")
    await architect.set_status(session, c, status="generating", error=None)
    await session.commit()
    master = request.app.state.master
    await architect.publish(master, c.id, c)
    master._spawn(architect.generate(master, c.id, body.note, body.structure_id))
    return await plan_out(session, v)
