"""Cover of a world, drawn in the creative studio on the project's workspace campaign.

Campaigns launched from a version of the world show it until they get a cover of their own.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.api.campaign_covers import HEADERS, CoverIn, CoverOut
from app.api.deps import SessionDep, UserDep
from app.core import campaign_covers as covers
from app.core.artwork import service
from app.core.authoring.projects import require_project
from app.core.campaigns import Viewer
from app.db.models import Campaign

router = APIRouter(prefix="/api/author/projects/{project_id}/cover", tags=["world-covers"])


async def workspace(session, user, project_id) -> Viewer:
    project = await require_project(session, user, project_id)
    return Viewer(user, await session.get(Campaign, project.workspace_campaign_id), None)


@router.get("", response_model=CoverOut)
async def cover_status(project_id: str, user: UserDep, session: SessionDep, request: Request):
    viewer = await workspace(session, user, project_id)
    enabled = request.app.state.campaign_cover_generator is not None
    return await covers.status(session, viewer, enabled, f"/api/author/projects/{project_id}/cover")


@router.post("", response_model=CoverOut)
async def create_cover(project_id: str, body: CoverIn, user: UserDep, session: SessionDep, request: Request):
    viewer = await workspace(session, user, project_id)
    state = request.app.state
    try:
        await service.generate(
            session,
            viewer,
            covers.RECIPE,
            viewer.campaign,
            body.request_key,
            body.regenerate,
            state.campaign_cover_generator,
            state.campaign_cover_translator,
            state.campaign_cover_media_dir,
        )
    except service.ArtworkPending as exc:
        raise HTTPException(409, detail={"code": "artwork_pending", "message": str(exc)}) from exc
    return await covers.status(session, viewer, True, f"/api/author/projects/{project_id}/cover")


@router.get("/{image_id}")
async def image(project_id: str, image_id: str, user: UserDep, session: SessionDep, request: Request):
    viewer = await workspace(session, user, project_id)
    path, mime = await covers.read_cover(session, viewer, image_id, request.app.state.campaign_cover_media_dir)
    return FileResponse(path, media_type=mime, headers=HEADERS)


@router.get("/{image_id}/thumbnail")
async def thumbnail(project_id: str, image_id: str, user: UserDep, session: SessionDep, request: Request):
    viewer = await workspace(session, user, project_id)
    path, mime = await covers.read_thumbnail(session, viewer, image_id, request.app.state.campaign_cover_media_dir)
    return FileResponse(path, media_type=mime, headers=HEADERS)
