# ruff: noqa: F811
import copy

from sqlalchemy import select

from app.db.models import Entity
from app.gateway.protocol import MapSketchExit
from tests.test_authoring_validation import _prepared, full_plan
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура


def _exits(entities, root_name, area_ref):
    root = next(e for e in entities if e.name == root_name)
    area = next(e for e in entities if e.id == root.state["areas"][area_ref])
    return area, [x for x in area.state["sketch"]["exits"] if x.get("route_ref")]


def test_route_ports_are_projected_as_map_exits_both_ways(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            entities = list(await s.scalars(select(Entity).where(Entity.campaign_id == cid)))
            source, out = _exits(entities, "Старый храм", "narthex")
            target, back = _exits(entities, "Старый маяк", "road")
            assert [x["route_ref"] for x in out] == ["r_port_light"] and out[0]["to"] == target.id
            assert [x["route_ref"] for x in back] == ["r_port_light"] and back[0]["to"] == source.id
            assert out[0]["cells"] == source.state["route_ports"]["r_port_light"]["cells"]
            MapSketchExit.model_validate(out[0])  # игровой протокол принимает географический выход

    _prepared(settings, body)


def test_one_way_route_has_no_return_exit(settings, _fast_retry):
    plan = full_plan()
    plan["routes"][0]["bidirectional"] = False
    plan = copy.deepcopy(plan)

    async def body(maker, pid, cid):
        async with maker() as s:
            entities = list(await s.scalars(select(Entity).where(Entity.campaign_id == cid)))
            _source, out = _exits(entities, "Старый храм", "narthex")
            _target, back = _exits(entities, "Старый маяк", "road")
            assert len(out) == 1 and not [x for x in back if x["route_ref"] == "r_port_light"]

    _prepared(settings, body, plan)
