"""Пространственный замысел места в каркасе (спецификация 2026-10-12, §3.1)."""

import copy

import pytest

from app.core import plot
from tests.test_plan import FakeCatalog, good_plan

TEMPLE = {
    "environment": "mixed",
    "scale": "medium",
    "parts": [
        {"ref": "road", "name": "Дорога у храма", "purpose": "дорога, ручей и мост", "outdoor": True},
        {"ref": "narthex", "name": "Притвор"},
        {"ref": "nave", "name": "Главный зал", "purpose": "колонны и алтарь"},
        {"ref": "chapel", "name": "Часовня", "required": True},
        {"ref": "crypt", "name": "Крипта", "below": True},
        {"ref": "vault", "name": "Тайник", "secret": True},
    ],
    "approaches": [{"name": "Дорога в деревню", "kind": "road"}],
    "links": ["loc_tavern"],
}


def _check(p):
    return plot.check(p, length="short", catalog=FakeCatalog(), excluded=[])


def test_plan_without_spatial_still_checks():
    p, errors = _check(good_plan())
    assert errors == [] and all("spatial" not in x for x in p["locations"])


def test_spatial_is_normalized():
    raw = good_plan()
    raw["locations"][2]["spatial"] = copy.deepcopy(TEMPLE)
    p, errors = _check(raw)
    assert errors == []
    sp = p["locations"][2]["spatial"]
    assert sp["schema_version"] == 1 and sp["parts"][1]["outdoor"] is False and sp["approaches"][0]["kind"] == "road"


@pytest.mark.parametrize(
    "mutate, text",
    [
        (lambda s: s["parts"][0].update(secret=True), "вход"),
        (lambda s: s.update(environment="indoor"), "indoor"),
        (lambda s: (s["parts"].pop(), s["parts"].append(dict(s["parts"][1]))), "повторяется"),
        (lambda s: s["parts"].extend([{"ref": f"x{i}", "name": "X"} for i in range(3)]), "parts"),
        (lambda s: s["parts"][3].update(secret=True), "тайная часть"),
        (lambda s: s["parts"][4].update(outdoor=True), "уровнем ниже"),
        (lambda s: s.update(links=["loc_nowhere"]), "нет места loc_nowhere"),
    ],
)
def test_spatial_errors_return_to_architect(mutate, text):
    raw = good_plan()
    sp = copy.deepcopy(TEMPLE)
    mutate(sp)
    raw["locations"][2]["spatial"] = sp
    _p, errors = _check(raw)
    assert any(e.startswith("локация loc_light: пространство") and text in e for e in errors), errors


def test_tool_spec_spatial_is_optional_and_revision_keeps_it():
    loc = plot.tool_spec()["function"]["parameters"]["properties"]["locations"]["items"]
    assert "spatial" in loc["properties"] and "spatial" not in loc["required"]
    rev_loc = plot.revision_spec()["function"]["parameters"]["properties"]["locations"]["items"]
    assert "spatial" in rev_loc["properties"]
    p, _ = _check(good_plan())
    new = {
        "id": "loc_temple",
        "name": "Храм",
        "template_id": "location.ruins",
        "role": "-",
        "mood": "-",
        "secret": "-",
        "spatial": copy.deepcopy(TEMPLE) | {"links": []},
    }
    merged, errors = plot.merge_revision(p, {"summary": "храм", "acts": copy.deepcopy(p["acts"]), "locations": [new]})
    merged, errors = plot.check(merged, length="short", catalog=FakeCatalog(), excluded=[], keep_state=True)
    assert errors == [] and merged["locations"][-1]["spatial"]["parts"][0]["ref"] == "road"


def test_architect_is_told_about_spatial():
    assert "spatial" in plot.SYSTEM
