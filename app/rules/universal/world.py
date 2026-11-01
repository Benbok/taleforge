"""Bounded authoring proposals; these are world facts, not player action outcomes."""

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.rules.universal.contracts import ClosedModel

Ref = str


_LOOKALIKES = str.maketrans("ABCEHKMOPTXaceopxy", "АВСЕНКМОРТХасеорху")
_CYRILLIC = re.compile("[А-Яа-яЁё]")
_LATIN = re.compile("[A-Za-z]")


def fix_mixed_script(value):
    """A word with Latin lookalikes inside Cyrillic ("Mapла") is a model slip, never a name: set the letters right.
    A word that is wholly Latin is left alone."""
    if not isinstance(value, str):
        return value
    return re.sub(
        r"\w+",
        lambda m: m.group().translate(_LOOKALIKES)
        if _CYRILLIC.search(m.group()) and _LATIN.search(m.group())
        else m.group(),
        value,
    )


def clip(limit):
    """Free-text hints are cosmetic: a model overshooting the limit must not void a whole scene plan."""
    return lambda value: value[:limit] if isinstance(value, str) else value


class WorldObject(ClosedModel):
    ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    kind: Literal["object", "npc", "creature"]
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1500)
    template: Literal["prop", "vessel", "wood_source", "water_source", "structure"] = "prop"
    material: Literal["wood", "plant", "stone"] = "stone"
    amount: int = Field(default=1, ge=1, le=10000, strict=True)
    hidden: bool = False
    hostile: bool = False
    # How a creature behaves when it is beaten: a fanatic never yields, a coward gives up soonest.
    temper: Literal["fanatic", "brave", "wary", "cowardly"] = "brave"

    _clean_text = field_validator("name", "description", mode="before")(fix_mixed_script)

    @model_validator(mode="before")
    @classmethod
    def ordinary_when_unknown(cls, data):
        """template and material only shape a prop: a value outside the lists ("creature" for a person, bone, iron)
        is a draft's slip, not worth a whole scene, so the object is made ordinary."""
        if isinstance(data, dict):
            data = dict(data)
            if data.get("template") not in {None, "prop", "vessel", "wood_source", "water_source", "structure"}:
                data["template"] = "prop"
            if data.get("material") not in {None, "wood", "plant", "stone"}:
                data["material"] = "stone"
            if data.get("temper") not in {None, "fanatic", "brave", "wary", "cowardly"}:
                data["temper"] = "brave"
        return data

    @model_validator(mode="after")
    def living_hostile(self):
        if self.hostile and self.kind == "object":
            raise ValueError("An ordinary object cannot be a hostile creature")
        return self


class WorldPassage(ClosedModel):
    ref: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    name: str = Field(min_length=1, max_length=100)
    destination: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=500)
    existing_destination_id: str | None = Field(default=None, max_length=32)
    kind: Literal["door", "stairs", "arch", "gap", "passage"] = "passage"
    state: Literal["open", "closed", "locked", "blocked"] = "open"
    bearing: Literal["n", "ne", "e", "se", "s", "sw", "w", "nw"] | None = None
    hidden: bool = False

    _clip_destination = field_validator("destination", mode="before")(clip(100))
    _clean_text = field_validator("name", "destination", "description", mode="before")(fix_mixed_script)

    @model_validator(mode="before")
    @classmethod
    def hint_from_name(cls, data):
        """The hint of where a way leads is cosmetic (the far place is made when someone first goes there): a draft
        that left it out is not worth a whole scene, the way's own name stands in for it."""
        if (
            isinstance(data, dict)
            and not data.get("existing_destination_id")
            and not str(data.get("destination") or "").strip()
        ):
            name = str(data.get("name") or "").strip()
            if name:
                data = {**data, "destination": name[:100]}
        return data

    @model_validator(mode="after")
    def destination_required(self):
        if not self.existing_destination_id and not self.destination.strip():
            raise ValueError("A passage needs a public destination hint")
        return self


class WorldLoot(ClosedModel):
    ref: str = Field(pattern=r"^loot_[12]$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=600)
    attribute: Literal["str", "dex"] = "str"

    _clean_text = field_validator("name", "description", mode="before")(fix_mixed_script)


class WorldScenePlan(ClosedModel):
    @model_validator(mode="before")
    @classmethod
    def unwrap_payload(cls, data):
        """A draft sometimes comes back as a call envelope, {"action": ..., "payload": {the plan}}."""
        if isinstance(data, dict) and "name" not in data and isinstance(data.get("payload"), dict):
            return data["payload"]
        return data

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=6000)
    objects: list[WorldObject] = Field(default_factory=list, max_length=16)
    passages: list[WorldPassage] = Field(default_factory=list, max_length=8)
    items: list[WorldLoot] = Field(default_factory=list, max_length=2)

    _clean_text = field_validator("name", "description", mode="before")(fix_mixed_script)

    @model_validator(mode="after")
    def unique_refs(self):
        refs = [o.ref for o in self.objects] + [p.ref for p in self.passages] + [i.ref for i in self.items]
        if len(refs) != len(set(refs)):
            raise ValueError("World references must be unique within a scene")
        return self


class WorldSceneReview(ClosedModel):
    verdict: Literal["pass", "revise"]
    message: str = Field(default="", max_length=1500)

    _clip_message = field_validator("message", mode="before")(clip(1500))
