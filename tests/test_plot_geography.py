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


def test_character_fields_survive_check_and_reach_the_master_only_when_near():
    p = good_plan()
    p["npcs"][0].update(character="угрюм, честен", speech="«Уходите, пока прилив»", knows="где культ")
    p["antagonists"][0].update(character="фанатична", on_meeting="поёт, не нападает")
    plan, errors = _check(p)
    assert not errors, errors
    npc, villain = plan["npcs"][0], plan["antagonists"][0]
    assert npc["speech"] == "«Уходите, пока прилив»" and villain["on_meeting"] == "поёт, не нападает"
    full = plot.render(plan)
    assert "угрюм, честен" in full and "фанатична" in full  # get_plot показывает всё
    now = plot.now_block(plan)
    assert "угрюм, честен" in now  # смотритель живёт в месте открытого узла: он рядом
    far = good_plan()
    far["npcs"][-1].update(character="далёкий персонаж", location_id=None)
    for act in far["acts"]:
        for node in act.get("nodes") or []:
            node["npc_ids"] = [i for i in node.get("npc_ids") or [] if i != far["npcs"][-1]["id"]]
    far_plan, _errors = _check(far)
    assert "далёкий персонаж" not in plot.now_block(far_plan)  # кто не рядом, тот не стоит токенов
    assert ("фанатична" in now) == any(
        villain["id"] in (n.get("npc_ids") or []) for n in plan["acts"][0].get("nodes") or []
    )


def test_plan_without_character_adds_nothing():
    plan, _errors = _check(good_plan())
    assert "Характер:" not in plot.now_block(plan) and "Характер:" not in plot.render(plan)


def test_schema_offers_character_fields():
    props = plot.tool_spec()["function"]["parameters"]["properties"]
    npc = props["npcs"]["items"]["properties"]
    villain = props["antagonists"]["items"]["properties"]
    assert {"character", "speech", "knows", "ties", "sways"} <= set(npc)
    assert {"character", "speech", "on_meeting", "if_foiled"} <= set(villain)
    assert "character" not in props["npcs"]["items"]["required"]  # необязательные: старые каркасы проходят
