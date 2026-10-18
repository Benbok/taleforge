# ruff: noqa: F811
import pytest
from sqlalchemy import select

from app.core.authoring.contracts import DraftPatch
from app.core.authoring.edits import accept_stale, apply_edits
from app.core.authoring.publication import PublishBlocked, publish_project
from app.core.authoring.validation import store_report, validate_project
from app.core.campaigns import Conflict
from app.db.models import AdventureVersion, AuthorProject
from tests.test_authoring_validation import _prepared
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура


async def validated(s, pid):
    project = await s.get(AuthorProject, pid)
    await store_report(s, project, await validate_project(s, project))
    await s.commit()
    return project


def test_publish_is_idempotent_and_immutable(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project = await validated(s, pid)
            rev = project.draft_revision
            v1 = await publish_project(s, project, rev, "p1")
            await s.commit()
            again = await publish_project(s, project, rev, "p1")
            assert again.id == v1.id and v1.version == 1
            with pytest.raises(Conflict):
                await publish_project(s, project, rev + 1, "p1")
            digest, summary = v1.source_digest, v1.public_summary
            assert summary["title"] and "secret" not in str(summary).lower()
            # правка проекта не меняет опубликованный bundle
            patch = DraftPatch.model_validate(
                {"operations": [{"op": "update_plot_object", "ref": "npc_warden", "fields": {"name": "Иной"}}]}
            )
            await apply_edits(s, project, patch, rev, "edit1")
            await s.commit()
            stored = await s.get(AdventureVersion, v1.id)
            assert stored.source_digest == digest
            assert "Иной" not in str(stored.bundle)

    _prepared(settings, body)


def test_publish_refused_without_fresh_report_or_with_stale_revision(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            rev = project.draft_revision
            with pytest.raises(Conflict) as raised:
                await publish_project(s, project, rev, "p1")  # отчёта ещё нет
            assert "validation_required" in str(raised.value)
            await s.rollback()
            await s.refresh(project)
            project = await validated(s, pid)
            with pytest.raises(Conflict) as raised:
                await publish_project(s, project, rev - 1, "p2")
            assert "stale_revision" in str(raised.value)
            await s.rollback()
            await s.refresh(project)
            patch = DraftPatch.model_validate({"operations": [{"op": "set_lore", "fields": {"tone": "новый"}}]})
            await apply_edits(s, project, patch, project.draft_revision, "e1")
            await s.commit()
            await s.refresh(project)
            with pytest.raises(Conflict) as raised:  # отчёт устарел после правки
                await publish_project(s, project, project.draft_revision, "p3")
            assert "validation_required" in str(raised.value)
            assert not list(await s.scalars(select(AdventureVersion)))

    _prepared(settings, body)


def test_publish_blocked_by_stale_dependency_then_v2_after_revalidation(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project = await validated(s, pid)
            project.dependencies = {**project.dependencies, "stale": ["layout:loc_port"]}
            await store_report(s, project, await validate_project(s, project))
            with pytest.raises(PublishBlocked) as raised:
                await publish_project(s, project, project.draft_revision, "p1")
            assert {i.code for i in raised.value.issues} == {"stale_result"}
            await s.rollback()
            await s.refresh(project)
            project = await validated(s, pid)
            v1 = await publish_project(s, project, project.draft_revision, "p2")
            await s.commit()
            v1_number, v1_digest = v1.version, v1.source_digest
            patch = DraftPatch.model_validate({"operations": [{"op": "set_lore", "fields": {"tone": "v2"}}]})
            await apply_edits(s, project, patch, project.draft_revision, "e2")
            await s.commit()
            project = await validated(s, pid)
            with pytest.raises(PublishBlocked):  # правка лора сделала сюжет устаревшим
                await publish_project(s, project, project.draft_revision, "p-blocked")
            await s.rollback()
            await s.refresh(project)
            await accept_stale(s, project, ["stage:plot"], project.draft_revision, "acc")
            await s.commit()
            project = await validated(s, pid)
            v2 = await publish_project(s, project, project.draft_revision, "p3")
            assert (v1_number, v2.version) == (1, 2) and v1_digest != v2.source_digest

    _prepared(settings, body)
