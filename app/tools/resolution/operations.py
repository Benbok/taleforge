"""Closed consequence vocabulary, reusing actual tool argument models."""

from functools import reduce
from operator import or_
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, create_model

from app.core.resolution.contracts import ActionRef, Contract
from app.tools.master.checks import EffectArgs, HazardArgs
from app.tools.master.entities import SpawnArgs, UpdateEntityArgs
from app.tools.master.items import DropArgs, GiveItemArgs, TakeItemArgs
from app.tools.master.knowledge import FactArgs
from app.tools.master.places import EnterRoomArgs, MoveArgs, RepositionArgs
from app.tools.master.scene import TimeArgs
from app.tools.standing import DeedArgs, ResolveArgs

OPERATION_TOOLS = {
    "time": ("advance_time", TimeArgs),
    "remove_item": ("take_item", TakeItemArgs),
    "drop_item": ("drop_item", DropArgs),
    "move": ("move", MoveArgs),
    "enter_room": ("enter_room", EnterRoomArgs),
    "reposition": ("reposition", RepositionArgs),
    "hazard": ("apply_hazard", HazardArgs),
    "effect": ("apply_effect", EffectArgs),
    "entity_update": ("update_entity", UpdateEntityArgs),
    "fact": ("learn_fact", FactArgs),
    "deed": ("record_deed", DeedArgs),
    "response": ("resolve_response", ResolveArgs),
    "neutral_npc": ("spawn_entity", SpawnArgs),
    "story_hook": ("learn_fact", FactArgs),
    "gift": ("give_item", GiveItemArgs),
}


class StoryHookOp(Contract):
    kind: Literal["story_hook"] = "story_hook"
    status: Literal["offer"] = "offer"
    subject_id: str
    character_ids: list[str] = Field(min_length=1, max_length=8)
    fact: str = Field(min_length=3, max_length=275)

    @property
    def args(self) -> FactArgs:
        return FactArgs(
            subject_id=self.subject_id, character_ids=self.character_ids, fact=f"Предложение (не принято): {self.fact}"
        )


def _operation(kind, args):
    if kind == "story_hook":
        return StoryHookOp
    fields = {"attitude": (Literal["neutral"], "neutral")} if kind == "neutral_npc" else {}
    strict_args = create_model(f"{args.__name__}Resolution", __base__=args, **fields)
    strict_args.model_config = ConfigDict(**{**args.model_config, "extra": "forbid"})
    strict_args.model_rebuild(force=True)
    return create_model(
        f"{kind.title().replace('_', '')}Consequence",
        __base__=Contract,
        kind=(Literal[kind], kind),
        args=(strict_args, ...),
    )


Consequence = Annotated[
    reduce(or_, (_operation(k, a) for k, (_, a) in OPERATION_TOOLS.items())), Field(discriminator="kind")
]


class ResolutionProposal(Contract):
    ref: ActionRef
    origin: Literal["normal", "creative", "fallback"]
    outcome: Literal["success", "partial", "failure"]
    reason: str = Field(min_length=1, max_length=1000)
    attempt_id: str | None = None
    operations: list[Consequence] = Field(default_factory=list, max_length=8)
