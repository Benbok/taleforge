# ruff: noqa: F811
"""Состояние NPC каркаса: «Раненый стражник» выходит в мир при смерти, а не с полными хитами шаблона."""

from app.core import plot
from app.db.models import Entity
from tests.game import run
from tests.layout_plan_pilot import temple_plan
from tests.test_layout_develop import _campaign
from tests.test_map import _ok, _play
from tests.test_plan import FakeCatalog, good_plan


def _check(p):
    return plot.check(p, length="short", catalog=FakeCatalog(), excluded=[])


def test_start_hp_follows_condition():
    assert plot.start_hp(11, None) == 11
    assert plot.start_hp(11, "healthy") == 11
    assert plot.start_hp(11, "wounded") == 6
    assert plot.start_hp(11, "dying") == 1
    assert plot.start_hp(11, "unconscious") == 0


def test_unknown_condition_is_an_error_and_schema_lists_the_values():
    p = good_plan()
    p["npcs"][0]["condition"] = "half-dead"
    _, errors = _check(p)
    assert any("condition" in e for e in errors), errors
    npc = plot.tool_spec()["function"]["parameters"]["properties"]["npcs"]["items"]["properties"]
    assert npc["condition"]["enum"] == list(plot.CONDITIONS)


def test_dying_npc_is_developed_with_one_hit_point(client, admin, settings):
    p = temple_plan()
    warden = next(n for n in p["npcs"] if n["id"] == "npc_warden")
    warden["condition"] = "dying"
    cid = _campaign(client, admin, settings, plan=p)
    out = _play(settings, cid, lambda ctx: _ok(ctx, "develop", {"sketch_id": "npc_warden", "details": "-"}))
    state = run(settings, lambda s: s.get(Entity, out["entity_id"])).state
    assert state["hp"] == 1 and state["hp_max"] > 1
    assert "при смерти" in plot.render(p)
