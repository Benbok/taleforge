import asyncio

import pytest
from sqlalchemy import select

from app.core.authoring.contracts import AuthorProjectCreate, DraftPatch
from app.core.authoring.edits import EditError, apply_edits
from app.core.authoring.projects import create_project
from app.core.campaigns import Conflict
from app.db.models import CampaignSecret, Event
from app.db.session import make_engine, make_sessionmaker
from tests.authoring_helpers import author


def sketch_plan():
    def loc(ref, name, parts, links=()):
        return {
            "id": ref,
            "name": name,
            "mood": "тихо",
            "role": "место",
            "secret": "тайна",
            "spatial": {
                "environment": "indoor",
                "parts": [{"ref": p, "name": p} for p in parts],
                "approaches": [{"name": "вход"}],
                "links": list(links),
            },
        }

    return {
        "locations": [
            loc("loc_cave", "Пещера", ("main", "crawl"), ("loc_tunnels",)),
            loc("loc_tunnels", "Туннели", ("junction",)),
        ],
        "npcs": [{"id": "npc_a", "name": "Лис", "location_id": "loc_cave", "role": "страж"}],
        "antagonists": [],
        "items": [{"ref": "item_key", "template_id": "object.key", "name": "Ключ"}],
        "routes": [{"ref": "r1", "from": "loc_cave/crawl", "to": "loc_tunnels/junction"}],
    }


def _run(settings, body):
    async def go():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as s:
                owner = await author(s)
                project = await create_project(s, owner, AuthorProjectCreate(title="W"))
                (await s.get(CampaignSecret, project.workspace_campaign_id)).plot = sketch_plan()
                await s.commit()
                await body(s, project)
        finally:
            await engine.dispose()

    asyncio.run(go())


def patch(*ops):
    return DraftPatch.model_validate({"operations": list(ops)})


async def plot_of(s, project):
    await s.refresh(project)
    return (await s.get(CampaignSecret, project.workspace_campaign_id)).plot


def test_rename_npc_keeps_maps_and_is_idempotent_and_logged(settings):
    async def body(s, project):
        rev = project.draft_revision
        p = patch({"op": "update_plot_object", "ref": "npc_a", "fields": {"name": "Рыжий лис"}})
        result = await apply_edits(s, project, p, rev, "k1")
        assert result.applied and result.affected == ()  # карту имя не затрагивает
        assert project.draft_revision > rev
        assert (await plot_of(s, project))["npcs"][0]["name"] == "Рыжий лис"
        again = await apply_edits(s, project, p, rev, "k1")
        assert again.event_id == result.event_id
        events = list(await s.scalars(select(Event).where(Event.tool == "author_edit")))
        assert len(events) == 1
        assert events[0].payload["before"]["plot"]["npcs"][0]["name"] == "Лис"
        assert events[0].payload["after"]["plot"]["npcs"][0]["name"] == "Рыжий лис"
        with pytest.raises(Conflict):  # тот же ключ с другой правкой
            await apply_edits(s, project, patch({"op": "set_lore", "fields": {"tone": "x"}}), rev, "k1")

    _run(settings, body)


def test_removing_used_place_returns_dependencies_and_changes_nothing(settings):
    async def body(s, project):
        before = await plot_of(s, project)
        result = await apply_edits(
            s, project, patch({"op": "remove_object", "ref": "loc_cave"}), project.draft_revision, "k"
        )
        assert not result.applied
        assert {(b.kind, b.ref) for b in result.blocked_by} >= {("npc", "npc_a"), ("route", "r1")}
        assert await plot_of(s, project) == before

    _run(settings, body)


def test_part_change_marks_layout_geometry_and_placements_stale(settings):
    async def body(s, project):
        spatial = {
            "environment": "indoor",
            "parts": [
                {"ref": "main", "name": "Вход"},
                {"ref": "crawl", "name": "Лаз"},
                {"ref": "extra", "name": "Ниша"},
            ],
            "approaches": [{"name": "вход"}],
        }
        result = await apply_edits(
            s,
            project,
            patch({"op": "edit_map", "location_ref": "loc_cave", "spatial": spatial}),
            project.draft_revision,
            "k",
        )
        kinds = {(a.kind, a.ref) for a in result.affected}
        assert {
            ("layout", "loc_cave"),
            ("geometry", "loc_cave"),
            ("placement", "loc_cave"),
            ("route_port", "r1"),
        } <= kinds
        assert "layout:loc_cave" in project.dependencies["stale"]

    _run(settings, body)


def test_stale_revision_and_invalid_edits_change_nothing(settings):
    async def body(s, project):
        before = await plot_of(s, project)
        rev = project.draft_revision
        with pytest.raises(Conflict):
            await apply_edits(s, project, patch({"op": "set_lore", "fields": {"tone": "x"}}), rev + 7, "k1")
        for bad in (
            {"op": "update_plot_object", "ref": "npc_a", "fields": {"template_id": "x"}},
            {"op": "update_plot_object", "ref": "nope", "fields": {"name": "x"}},
            {"op": "upsert_route", "ref": "r2", "from": "loc_cave/ghost", "to": "loc_tunnels/junction"},
            {"op": "edit_map", "location_ref": "loc_cave", "spatial": {"parts": []}},
            {"op": "set_lore", "fields": {"hack": "x"}},
        ):
            with pytest.raises(EditError):
                await apply_edits(s, project, patch(bad), rev, "k-bad")
            await s.rollback()
            await s.refresh(project)
            assert project.draft_revision == rev
        assert await plot_of(s, project) == before

    _run(settings, body)


def test_character_text_allows_long_fields_and_names_the_rejected_one():
    from app.core.authoring.edits import TEXT_LIMIT, _apply

    plan = {"npcs": [{"id": "npc_a", "name": "Лис"}]}
    long_ok = "ж" * TEXT_LIMIT
    ok = {"op": "update_plot_object", "ref": "npc_a", "fields": {"character": long_ok}}
    new_plan, _, _ = _apply(plan, {}, patch(ok))
    assert new_plan["npcs"][0]["character"] == long_ok
    assert TEXT_LIMIT >= 2000

    too_long = {"op": "update_plot_object", "ref": "npc_a", "fields": {"knows": "ж" * (TEXT_LIMIT + 1)}}
    with pytest.raises(EditError) as exc:
        _apply(plan, {}, patch(too_long))
    assert exc.value.code == "invalid_field" and "npc_a.knows" in str(exc.value)

    with pytest.raises(EditError) as exc:
        _apply(plan, {}, patch({"op": "update_plot_object", "ref": "npc_a", "fields": {"name": "  "}}))
    assert "npc_a.name" in str(exc.value)
