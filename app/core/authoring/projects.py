"""Author ownership checks and creation of an isolated generator workspace."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import CatalogError, resolve_chain
from app.core.authoring.contracts import AuthorProjectCreate
from app.core.campaigns import AccessDenied, Conflict, NotFound, create_world, is_admin
from app.db.models import AuthorProject, Campaign, ContentPack, User
from app.rules.dnd5e.engine import Dnd5eEngine


async def author_write(session: AsyncSession, project: AuthorProject, expected_revision: int) -> None:
    """Lock the draft before checking inputs; the shared world guard advances it."""
    # Match the world guard's lock order: campaign first, then project. Taking
    # these in reverse order could deadlock a worker against a manual edit.
    await session.execute(
        update(Campaign)
        .where(Campaign.id == project.workspace_campaign_id)
        .values(world_revision=Campaign.world_revision)
        .execution_options(synchronize_session=False)
    )
    matched = await session.scalar(
        update(AuthorProject)
        .where(AuthorProject.id == project.id, AuthorProject.draft_revision == expected_revision)
        .values(draft_revision=AuthorProject.draft_revision)
        .returning(AuthorProject.id)
        .execution_options(synchronize_session=False)
    )
    if matched is None:
        raise Conflict("stale_revision")
    from app.core.world_tx import world_write

    await world_write(session, project.workspace_campaign_id)


async def require_project(session: AsyncSession, user: User, project_id: str) -> AuthorProject:
    project = await session.get(AuthorProject, project_id)
    if not is_admin(user) or project is None or project.owner_id != user.id or project.archived_at is not None:
        raise NotFound("проект не найден")
    return project


async def create_project(session: AsyncSession, owner: User, request: AuthorProjectCreate) -> AuthorProject:
    if not is_admin(owner):
        raise AccessDenied("проекты создаёт только Admin")
    pack = None
    if request.pack_id:
        if not request.pack_version:
            raise Conflict("укажите версию пакета")
        pack = await session.get(ContentPack, (request.pack_id, request.pack_version))
        if pack is None:
            raise NotFound("пакет не найден")
    world = await create_world(
        session,
        owner,
        name=request.title,
        ruleset_version=Dnd5eEngine.version,
        pack=pack,
        difficulty=request.difficulty,
        players=None,
        master={**request.master.model_dump(), "type": "agent"},
        owner_plays=False,
        brief=request.brief.model_dump(exclude_defaults=True),
        purpose="author_workspace",
        settings={
            "tts_enabled": False,
            "tts_intro_enabled": False,
            "audio_enabled": False,
            "narrative_mode": "strict",
            "scene_generation": True,
            "scene_generation_llm": True,
        },
    )
    try:
        world.content_chain = await resolve_chain(session, pack)
    except CatalogError as exc:
        if pack is not None:
            raise Conflict(str(exc)) from exc
    project = AuthorProject(
        owner_id=owner.id, title=request.title, workspace_campaign_id=world.id, budget_usd=request.budget_usd
    )
    session.add(project)
    await session.flush()
    return project
