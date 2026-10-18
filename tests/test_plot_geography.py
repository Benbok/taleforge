from app.core import plot
from tests.test_plan import FakeCatalog, good_plan


def _check(p):
    return plot.check(p, length="short", catalog=FakeCatalog(), excluded=[], level_cap=20)


def test_architect_plan_keeps_regions_and_routes():
    p = good_plan()
    p["regions"] = [{"id": "reg_coast", "name": "Побережье"}]
    for loc in p["locations"]:
        loc["region"] = "reg_coast"
    p["routes"] = [{"ref": "r_port_tavern", "from": "loc_port", "to": "loc_tavern"}]
    plan, errors = _check(p)
    assert not errors, errors
    assert plan["regions"][0]["id"] == "reg_coast" and plan["routes"][0]["ref"] == "r_port_tavern"
    assert all(loc["region"] == "reg_coast" for loc in plan["locations"])


def test_architect_plan_rejects_broken_geography():
    p = good_plan()
    p["regions"] = [{"id": "a", "name": "A", "parent": "b"}, {"id": "b", "name": "B", "parent": "a"}]
    _plan, errors = _check(p)
    assert any("parent_cycle" in e for e in errors)
    p = good_plan()
    p["routes"] = [{"ref": "r", "from": "loc_port", "to": "loc_nowhere"}]
    _plan, errors = _check(p)
    assert any("unknown_node" in e for e in errors)


def test_tool_schema_offers_regions_and_routes():
    props = plot.tool_spec()["function"]["parameters"]["properties"]
    assert "regions" in props and "routes" in props
    assert "region" in props["locations"]["items"]["properties"]
