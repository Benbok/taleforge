# ruff: noqa: F811
import asyncio
import copy
from types import SimpleNamespace

from sqlalchemy import select

from app.core.authoring import jobs
from app.core.authoring.materialization import prepare_world
from app.core.authoring.runner import AuthorRunner
from app.core.authoring.validation import validate_project
from app.core.world_generation.service import Orchestrator
from app.db.models import AuthorJob, AuthorProject, CampaignSecret, Entity
from app.gateway.coordination import InMemoryCoordination
from tests.layout_plan_pilot import TEMPLE_SPATIAL
from tests.test_authoring_materialization import _prepared_project, _with_maker, homed_plan
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура


def full_plan():
    plan = homed_plan()
    for loc in plan["locations"]:
        if loc["id"] in ("loc_light", "loc_tavern", "loc_crypt"):
            loc["spatial"] = copy.deepcopy(TEMPLE_SPATIAL)
    plan["routes"] = [
        {"ref": "r_port_light", "from": "loc_port/narthex", "to": "loc_light/road"},
        {"ref": "r_port_tavern", "from": "loc_port/road", "to": "loc_tavern/road"},
        {"ref": "r_tavern_crypt", "from": "loc_tavern/crypt", "to": "loc_crypt/road"},
    ]
    plan["items"] = [
        {
            "ref": "item_key",
            "template_id": "item.torch",
            "name": "Ржавый ключ",
            "key": True,
            "placement": {"ref": "item_key", "location_ref": "loc_port", "area_ref": "chapel"},
        },
        {
            "ref": "item_chest",
            "template_id": "item.torch",
            "name": "Окованный сундук",
            "container": True,
            "placement": {"ref": "item_chest", "location_ref": "loc_port", "area_ref": "nave"},
        },
        {
            "ref": "item_seal",
            "template_id": "item.torch",
            "name": "Печать культа",
            "placement": {"ref": "item_seal", "location_ref": "loc_port", "container_ref": "item_chest"},
        },
        {
            "ref": "item_letter",
            "template_id": "item.torch",
            "name": "Письмо смотрителя",
            "placement": {"ref": "item_letter", "location_ref": "loc_port", "container_ref": "npc_warden"},
        },
    ]
    return plan


def _codes(report):
    return {(i.code, i.object_ref) for i in report.errors}


def _prepared(settings, body, plan=None):
    pid, cid = _prepared_project(settings, plan or full_plan())

    async def go(maker):
        report = await prepare_world(maker, pid, Orchestrator(InMemoryCoordination()))
        assert report.complete, report
        await body(maker, pid, cid)

    _with_maker(settings, go)


def test_prepared_world_validates_clean_and_report_is_revision_bound(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            report = await validate_project(s, project)
            assert not report.errors, report.errors
            assert report.source_revision == project.draft_revision
            assert report.coverage["parts_ready"] == report.coverage["parts_total"] > 0
            assert report.coverage["routes"] == 3 and report.coverage["items"] == 4

    _prepared(settings, body)


def test_port_cell_behind_wall_is_an_unreachable_port(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            light = next(
                e for e in await s.scalars(select(Entity).where(Entity.campaign_id == cid)) if e.name == "Старый маяк"
            )
            area_id = light.state["areas"]["road"]
            area = await s.get(Entity, area_id)
            sketch = copy.deepcopy(area.state["sketch"])
            cell = area.state["route_ports"]["r_port_light"]["cells"][0]
            sketch["walls"] = [*sketch.get("walls", []), cell]  # граф маршрута цел, клетка выхода заложена стеной
            area.state = {**area.state, "sketch": sketch}
            report = await validate_project(s, project)
            assert ("unreachable_port", "r_port_light") in _codes(report)

    _prepared(settings, body)


def test_key_only_in_text_and_unplaced_actor_are_errors(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            secret = await s.get(CampaignSecret, cid)
            plan = copy.deepcopy(secret.plot)
            plan["items"].append({"ref": "item_text", "template_id": "item.torch", "name": "Только в тексте"})
            plan["npcs"][0]["entity_id"] = None
            secret.plot = plan
            report = await validate_project(s, project)
            codes = _codes(report)
            assert ("missing_item", "item_text") in codes
            assert ("unplaced_actor", plan["npcs"][0]["id"]) in codes

    _prepared(settings, body)


def test_secret_optional_part_is_not_an_error_but_missing_map_is(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            assert not [i for i in (await validate_project(s, project)).errors if "vault" in str(i.object_ref)]
            port = next(
                e for e in await s.scalars(select(Entity).where(Entity.campaign_id == cid)) if e.name == "Старый храм"
            )
            area = await s.get(Entity, port.state["areas"]["chapel"])
            area.state = {k: v for k, v in area.state.items() if k != "sketch"}
            report = await validate_project(s, project)
            assert ("missing_geometry", "loc_port/chapel") in _codes(report)

    _prepared(settings, body)


def test_conditional_route_differs_from_missing_path(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            secret = await s.get(CampaignSecret, cid)
            plan = copy.deepcopy(secret.plot)
            plan["routes"][0]["hidden"] = True  # тайный путь — условие
            secret.plot = plan
            report = await validate_project(s, project)
            assert ("unreachable_location", "loc_light") not in _codes(report)
            assert any(w.code == "conditional_access" and w.object_ref == "loc_light" for w in report.warnings)
            plan["routes"] = []  # пути нет вовсе
            secret.plot = plan
            report = await validate_project(s, project)
            assert ("unreachable_location", "loc_light") in _codes(report)

    _prepared(settings, body)


def test_stale_and_open_jobs_block_and_validate_stage_does_not_move_revision(settings, _fast_retry):
    async def body(maker, pid, cid):
        svc = SimpleNamespace(maker=maker, llm=None, bus=None, coordination=InMemoryCoordination())
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            rev = project.draft_revision
            receipt = await jobs.request_stage(s, project, "validate", None, rev, "v1")
            await s.commit()
        await AuthorRunner(svc).run_due()
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            assert (await s.get(AuthorJob, receipt.job_id)).status == "ready"
            assert project.draft_revision == rev
            assert project.validation_report["source_revision"] == rev
            project.dependencies = {**project.dependencies, "stale": ["layout:loc_port"]}
            report = await validate_project(s, project)
            assert ("stale_result", "layout:loc_port") in _codes(report)

    _prepared(settings, body)


def test_validation_never_calls_a_model(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            await validate_project(s, project)  # conftest блокирует live LLM: вызов упал бы

    _prepared(settings, body)


_ = asyncio


def test_items_go_into_containers_and_npc_hands_and_anchors_are_placed(settings, _fast_retry):
    async def body(maker, pid, cid):
        from app.db.models import PlotAnchorBinding

        async with maker() as s:
            entities = list(await s.scalars(select(Entity).where(Entity.campaign_id == cid)))
            by_ref = {(e.state or {}).get("item_ref"): e for e in entities if (e.state or {}).get("item_ref")}
            chest = by_ref["item_chest"]
            assert chest.state["world_object"]["role"] == "container"
            assert by_ref["item_seal"].state["world_object"]["container_id"] == chest.id
            warden = next(e for e in entities if (e.state or {}).get("plot_id") == "npc_warden")
            assert by_ref["item_letter"].state["world_object"]["container_id"] == warden.id
            bindings = list(await s.scalars(select(PlotAnchorBinding).where(PlotAnchorBinding.campaign_id == cid)))
            assert bindings and all(b.state == "materialized" and b.holder_entity_id for b in bindings)
            carriers = [e for e in entities if (e.state or {}).get("plot_anchor")]
            assert carriers  # носитель зацепки уже лежит в подготовленном участке
            project = await s.get(AuthorProject, pid)
            report = await validate_project(s, project)
            assert not report.errors, report.errors
            by_ref["item_seal"].state = {
                **by_ref["item_seal"].state,
                "world_object": {**by_ref["item_seal"].state["world_object"], "container_id": None},
            }
            report = await validate_project(s, project)
            assert ("missing_item", "item_seal") in _codes(report)

    _prepared(settings, body)


def test_only_latest_attempt_of_a_stage_counts(settings, _fast_retry):
    async def body(maker, pid, cid):
        from app.db.models import AuthorJob

        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            for i, status in enumerate(("failed", "ready")):
                s.add(
                    AuthorJob(
                        project_id=pid,
                        stage="lore",
                        input_digest=f"d{i}",
                        source_revision=1,
                        status=status,
                        request_key=f"k{i}",
                        request_digest="x",
                    )
                )
                await s.flush()
            s.add(
                AuthorJob(
                    project_id=pid,
                    stage="editor",
                    input_digest="e",
                    source_revision=1,
                    status="failed",
                    request_key="ed",
                    request_digest="x",
                )
            )
            await s.flush()
            report = await validate_project(s, project)
            assert not [i for i in report.errors if i.code == "preparation_blocked"], report.errors

    _prepared(settings, body)


def test_world_overview_lists_areas_passages_routes_and_residents(settings, _fast_retry):
    async def body(maker, pid, cid):
        from app.api.authoring import world_overview
        from app.db.models import User

        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            owner = await s.get(User, project.owner_id)
            view = await world_overview(pid, s, owner)
        by_ref = {loc.ref: loc for loc in view.locations}
        port = by_ref["loc_port"]
        assert {a.area_ref for a in port.areas} >= {"narthex", "chapel"}
        assert any(a.entry for a in port.areas) and any(a.secret for a in port.areas)
        assert port.passages and all(p.from_area for p in port.passages)
        assert any("Ржавый ключ" in a.items for a in port.areas)  # ключевой предмет виден в своём участке
        assert any(a.npcs for loc in view.locations for a in loc.areas)
        assert {r.ref for r in view.routes} >= {"r_port_light", "r_port_tavern"}

    _prepared(settings, body)
