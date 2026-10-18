"""Hand-made content instead of paid generation: import a plot made elsewhere, copy the task for an outside model.

An imported plot passes the same server check as the architect's, so the rest of the pipeline treats it exactly
like a generated one. Nothing here calls a model.
"""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import campaign_catalog
from app.core import plot
from app.core.authoring.projects import author_write
from app.core.campaigns import Conflict
from app.db.models import AuthorProject, Campaign, Event


class ImportRejected(Conflict):
    """The imported content failed the server check; nothing was changed."""

    def __init__(self, errors: list[str]):
        super().__init__("import_rejected")
        self.errors = errors


def _key(project_id: str, request_key: str) -> str:
    return hashlib.sha256(f"{project_id}:import:{request_key}".encode()).hexdigest()[:64]


async def import_plot(
    session: AsyncSession, project: AuthorProject, raw: dict, expected_revision: int, request_key: str
) -> dict:
    from app.agents import architect
    from app.core.authoring.pipeline import clear_world, downstream, output_digest

    key = _key(project.id, request_key)
    done = await session.scalar(
        select(Event).where(Event.campaign_id == project.workspace_campaign_id, Event.idempotency_key == key)
    )
    if done is not None:
        return done.payload["result"]
    await author_write(session, project, expected_revision)
    world = await session.get(Campaign, project.workspace_campaign_id)
    catalog = await campaign_catalog(session, world)
    checked, errors = plot.check(
        json.loads(json.dumps(raw)),  # check() normalizes in place; keep the author's payload intact
        length=architect.length_of(world),
        catalog=catalog,
        excluded=list((world.settings or {}).get("excluded_themes") or []),
        level_cap=20,
    )
    if checked is None:
        raise ImportRejected(errors)
    row = await architect.apply_plan(session, world, checked, checked.get("structure_id"), "импорт автора")
    cleared = await clear_world(session, project.id, world.id)
    await session.refresh(project)
    deps = dict(project.dependencies or {})
    digest = output_digest({"imported": checked})
    stale = set(deps.get("stale") or []) - {"stage:plot"}
    if deps.get("plot") not in (None, digest):
        stale |= {f"stage:{down}" for down in downstream("plot") if down in deps}
    deps.update(plot=digest, stale=sorted(stale))
    project.dependencies = deps
    result = {"plan_version_id": row.id, "cleared_entities": cleared, "source": "import"}
    session.add(
        Event(
            campaign_id=world.id,
            tool="author_edit",
            hidden=True,
            idempotency_key=key,
            payload={"request_key": request_key, "import": "plot", "result": result},
        )
    )
    await session.flush()
    return result


async def task_for(session: AsyncSession, project: AuthorProject, stage: str) -> dict:
    """The exact system prompt, input and answer schema of a stage, to run it in any outside model by hand."""
    world = await session.get(Campaign, project.workspace_campaign_id)
    if stage == "lore":
        from app.core.authoring import lore

        brief = json.dumps(world.brief or {}, ensure_ascii=False)
        return {
            "stage": "lore",
            "system": lore.SYSTEM,
            "user": f"Название приключения: {world.name}\nАнкета автора: {brief}",
            "schema": lore.tool_spec()["function"]["parameters"],
            "how": "Ответ — один JSON-объект по схеме. Вставьте его в «Импорт лора».",
        }
    if stage == "plot":
        from app.agents import architect

        text, _sid = await architect.build_input(session, world)
        return {
            "stage": "plot",
            "system": plot.SYSTEM,
            "user": text,
            "schema": plot.tool_spec()["function"]["parameters"],
            "how": "Ответ — один JSON-объект каркаса по схеме. Вставьте его в «Импорт каркаса»: сервер проверит его.",
        }
    raise Conflict("задание доступно для этапов lore и plot")
