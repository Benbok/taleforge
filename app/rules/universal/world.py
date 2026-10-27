"""Bounded authoring proposals; these are world facts, not player action outcomes."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.rules.universal.contracts import ClosedModel

Ref = str


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

    @model_validator(mode="after")
    def destination_required(self):
        if not self.existing_destination_id and not self.destination.strip():
            raise ValueError("A passage needs a public destination hint")
        return self


class WorldScenePlan(ClosedModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=6000)
    objects: list[WorldObject] = Field(default_factory=list, max_length=16)
    passages: list[WorldPassage] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def unique_refs(self):
        refs = [o.ref for o in self.objects] + [p.ref for p in self.passages]
        if len(refs) != len(set(refs)):
            raise ValueError("World references must be unique within a scene")
        return self


class WorldSceneReview(ClosedModel):
    verdict: Literal["pass", "revise"]
    message: str = Field(default="", max_length=1500)

    _clip_message = field_validator("message", mode="before")(clip(1500))
