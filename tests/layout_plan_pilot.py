"""Пилот поставки 3: каркас храма с пространством, мандат и ответ технической модели для тестов."""

from __future__ import annotations

import copy

from app.core import plot
from app.core.layout.spatial import Holder, Mandate, SpatialPlan
from tests.layout_pilot import pilot_intent
from tests.test_plan import FakeCatalog, good_plan

TEMPLE_SPATIAL = {
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
}


def temple_mandate(anchors=(("clue_relic", "Журнал смотрителя"),), residents=(("npc:npc_warden", "Бертольд"),)):
    return Mandate(
        place="Старый храм",
        mood="Ветер в разбитых окнах",
        spatial=SpatialPlan.model_validate(TEMPLE_SPATIAL),
        anchors=[Holder(key=k, name=n) for k, n in anchors],
        residents=[Holder(key=k, name=n) for k, n in residents],
    )


def temple_plan() -> dict:
    """Каркас good_plan: Солёная бухта стала храмом с пространством; смотритель живёт там, журнал — носитель."""
    p = good_plan()
    port = p["locations"][0]
    port.update(
        name="Старый храм",
        template_id="location.ruins",
        mood="Ветер в разбитых окнах",
        spatial=copy.deepcopy(TEMPLE_SPATIAL),
    )
    p["reveals"][0]["clues"][1]["carrier"] = {"name": "Журнал смотрителя", "description": "Страницы вырваны."}
    checked, errors = plot.check(p, length="short", catalog=FakeCatalog(), excluded=[])
    assert errors == [], errors
    return checked


def model_layout(keys: list[str]) -> dict:
    """Ответ модели: замысел пилота поставки 1 без outside_id; носители — в часовне, жители — у дороги."""
    raw = pilot_intent().model_dump(mode="json")
    raw.pop("schema_version", None)
    for ap in raw["approaches"]:
        ap.pop("outside_id", None)
    parts = []
    for part in raw["parts"]:
        part = {k: v for k, v in part.items() if v is not None}
        part["anchors"] = []
        if part["part_ref"] == "chapel":
            part["anchors"] = [k for k in keys if not k.startswith("npc:")]
            part["required"] = True
        if part["part_ref"] == "road":
            part["anchors"] = [k for k in keys if k.startswith("npc:")]
        parts.append(part)
    raw["parts"] = parts
    raw["bands"] = [{k: v for k, v in b.items() if v is not None} for b in raw["bands"]]
    raw["approaches"] = [{k: v for k, v in a.items() if v is not None} for a in raw["approaches"]]
    return raw
