# ruff: noqa: F811
import json

import pytest
from sqlalchemy import select

from app.core.authoring.references import find_leaks
from app.core.authoring.snapshot import SnapshotError, export_bundle, validate_bundle
from app.db.models import AuthorProject, Entity, GeographyNode, PlotAnchorBinding, WorldGenerationState
from tests.test_authoring_validation import _prepared
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура


def test_export_has_maps_ports_anchors_geography_and_no_workspace_ids(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            bundle = await export_bundle(s, project)
            source_ids = {e.id for e in await s.scalars(select(Entity).where(Entity.campaign_id == cid))}
            source_ids |= {r.id for r in await s.scalars(select(WorldGenerationState))}
            source_ids |= {a.id for a in await s.scalars(select(PlotAnchorBinding))}
            source_ids |= {n.id for n in await s.scalars(select(GeographyNode))}
            source_ids |= {cid, pid}
        body_json = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False)
        assert not find_leaks(bundle.model_dump(mode="json"), source_ids)
        assert not [i for i in source_ids if i in body_json]  # ни одного id рабочего мира даже внутри текста
        assert not validate_bundle(bundle)
        sketches = [e for e in bundle.entities if e.state.get("sketch")]
        assert sketches and any(e.state.get("route_ports") for e in sketches)
        assert bundle.anchors and bundle.geography_links and len(bundle.geography_nodes) >= 4
        assert any(e.kind == "creature" for e in bundle.entities)
        assert any(e.state.get("item_ref") == "item_key" for e in bundle.entities)
        for forbidden in ("lease_token", "characters", "messages", "game_session", "explored"):
            assert forbidden not in body_json
        # внешние End.place_id и manifests ссылаются только на логические refs
        refs = {e.ref for e in bundle.entities}
        assert all(g.target in refs for g in bundle.generations)

    _prepared(settings, body)


def test_unknown_reference_structure_blocks_export(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            project = await s.get(AuthorProject, pid)
            npc = next(
                e for e in await s.scalars(select(Entity).where(Entity.campaign_id == cid)) if e.kind == "creature"
            )
            npc.state = {**npc.state, "mystery": {"points_at": npc.id}}
            with pytest.raises(SnapshotError) as raised:
                await export_bundle(s, project)
            assert raised.value.code == "unsupported_reference" and "mystery" in raised.value.where
            npc.state = {k: v for k, v in npc.state.items() if k != "mystery"}
            npc.state = {**npc.state, "note": npc.id}  # id спрятан в скаляре: его поймает проверка утечек
            with pytest.raises(SnapshotError):
                await export_bundle(s, project)

    _prepared(settings, body)


def test_validate_bundle_reports_dangling_refs(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            bundle = await export_bundle(s, await s.get(AuthorProject, pid))
        bundle.entities[0].location = "e9999"
        assert [i.code for i in validate_bundle(bundle)] == ["unresolved_ref"]

    _prepared(settings, body)
