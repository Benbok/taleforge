from types import SimpleNamespace

import pytest

from app.core.geography.compiler import compile_plan
from app.core.geography.contracts import GeographyError, GeographyView, RouteEndpoint
from app.core.geography.ports import resolve_port
from app.core.topology import location_exits


def ent(id, name, state=None, kind="location", location_id=None):
    return SimpleNamespace(id=id, name=name, kind=kind, state=state or {}, location_id=location_id)


def world():
    cave = ent(
        "e_cave",
        "Пещера",
        {"areas": {"main": "e_fall", "part_fall": "e_fall", "part_crawl": "e_crawl"}},
    )
    fall = ent("e_fall", "Обвал", {"complex": {"root_id": "e_cave", "area_ref": "part_fall"}})
    crawl = ent("e_crawl", "Узкий лаз", {"complex": {"root_id": "e_cave", "area_ref": "part_crawl"}})
    tunnels = ent("e_tun", "Туннели", {"areas": {"part_junction": "e_junc"}})
    junc = ent("e_junc", "Развилка", {"complex": {"root_id": "e_tun", "area_ref": "part_junction"}})
    entities = {e.id: e for e in (cave, fall, crawl, tunnels, junc)}
    plan = {
        "locations": [
            {
                "id": "loc_cave",
                "name": "Пещера",
                "spatial": {"parts": [{"ref": "main"}, {"ref": "part_fall"}, {"ref": "part_crawl"}]},
            },
            {"id": "loc_tunnels", "name": "Туннели", "spatial": {"parts": [{"ref": "part_junction"}]}},
        ],
        "routes": [{"ref": "r_crawl", "from": "loc_cave/part_crawl", "to": "loc_tunnels/part_junction"}],
    }
    draft = compile_plan(plan)
    view = GeographyView(
        nodes=tuple(
            n.model_copy(update={"entity_id": {"loc_cave": "e_cave", "loc_tunnels": "e_tun"}[n.ref]})
            for n in draft.nodes
        ),
        links=draft.links,
        start_ref=draft.start_ref,
    )
    return entities, view


def test_port_resolves_to_exact_part_not_root_or_first_entrance():
    entities, view = world()
    ids = {n.ref: n.entity_id for n in view.nodes}
    port = resolve_port(entities, ids, RouteEndpoint(node_ref="loc_cave", area_ref="part_crawl"))
    assert port.area_id == "e_crawl"
    assert port.area_id not in ("e_cave", "e_fall")


def test_mismatched_port_is_an_error_not_a_substitute():
    entities, view = world()
    ids = {n.ref: n.entity_id for n in view.nodes}
    with pytest.raises(GeographyError) as raised:
        resolve_port(entities, ids, RouteEndpoint(node_ref="loc_cave", area_ref="part_missing"))
    assert raised.value.code == "unresolved_port"
    with pytest.raises(GeographyError) as raised:
        resolve_port(entities, ids, RouteEndpoint(node_ref="loc_cave"))
    assert raised.value.code == "port_area_required"


def test_exit_leaves_from_crawl_only_and_returns_both_ways():
    entities, view = world()
    out = location_exits(entities["e_crawl"], None, entities, geography=view)
    assert [(e.target_id, e.route_ref) for e in out if e.route_ref] == [("e_junc", "r_crawl")]
    assert not [
        e for e in location_exits(entities["e_fall"], None, entities, geography=view) if e.route_ref == "r_crawl"
    ]
    back = location_exits(entities["e_junc"], None, entities, geography=view)
    assert [(e.target_id, e.route_ref) for e in back if e.route_ref == "r_crawl"] == [("e_crawl", "r_crawl")]


def test_legacy_call_without_geography_is_unchanged():
    entities, view = world()
    assert all(e.route_ref is None for e in location_exits(entities["e_crawl"], None, entities))
