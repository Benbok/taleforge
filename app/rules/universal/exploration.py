"""Closed semantic actions and server budgets for stage2A. No storage or model I/O."""

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import Field, model_validator

from app.rules.universal.contracts import AbilityKey, ClosedModel, Count
from app.rules.universal.profiles import ActionOutcome, CheckNarration
from app.rules.universal.progression import RewardIntent

SourceKind = Literal["mundane", "supernatural", "item"]
ResolutionKind = Literal["automatic", "check", "attack", "resistance"]
EffectKind = Literal[
    "weapon_attack",
    "equip",
    "unequip",
    "guard",
    "damage_over_time",
    "observe",
    "speak",
    "wait",
    "hold_breath",
    "move",
    "cosmetic",
    "illumination",
    "camouflage",
    "change_form",
    "create_object",
    "take",
    "place",
    "give",
    "fill",
    "pour",
    "empty",
    "consume",
    "dismiss",
    "damage",
    "heal",
    "cannot_move",
    "cannot_act",
    "cannot_target",
    "check_bonus",
    "defense_bonus",
    "free_effect",
    "command",
]
ObjectTemplate = Literal["vessel", "wood_source", "water_source", "energy_tonic", "observer", "structure", "creature"]
Scale = Literal["tiny", "small", "medium", "large", "huge"]
Sturdiness = Literal["fragile", "ordinary", "sturdy"]
# Energy per hero level and per six-second unit for something of this size; the model judges the size.
SCALE_PRICE = {"tiny": 1, "small": 2, "medium": 4, "large": 8, "huge": 16}
LEADS_SCALES = frozenset({"large", "huge"})
DEFAULT_EFFECT_SECONDS = 18
MAX_EFFECT_SECONDS = 604800  # a week: only keeps the whole numbers sane, the price is the real limit


class InsufficientEnergy(ValueError):
    """The hero cannot pay for this spell; the numbers help the model choose less and tell what was missing."""

    def __init__(self, need, have):
        self.need, self.have = need, have
        super().__init__(f"Недостаточно энергии: нужно {need}, есть {have}")


class FormBlocked(ValueError):
    """The hero's current form forbids the action; the reason is safe and useful to show the player."""


TIMED_KINDS = frozenset(
    {
        "guard",
        "damage_over_time",
        "create_object",
        "free_effect",
        "illumination",
        "camouflage",
        "change_form",
        "hold_breath",
        "cannot_move",
        "cannot_act",
        "cannot_target",
        "check_bonus",
        "defense_bonus",
    }
)
ORDINARY_KINDS = frozenset(
    {
        "weapon_attack",
        "equip",
        "unequip",
        "guard",
        "observe",
        "speak",
        "move",
        "wait",
        "hold_breath",
        "take",
        "place",
        "give",
        "fill",
        "pour",
        "empty",
        "consume",
        "dismiss",
        "command",
    }
)
MAGIC_KINDS = frozenset(
    {
        "damage_over_time",
        "cosmetic",
        "illumination",
        "camouflage",
        "change_form",
        "create_object",
        "free_effect",
        "damage",
        "heal",
        "cannot_move",
        "cannot_act",
        "cannot_target",
        "check_bonus",
        "defense_bonus",
    }
)
# An ordinary deed may leave a remembered note (a torch made of a board): it is a fact for the writer, costs no
# energy, and is not magic. The review still reads it, because it is never a plain action.
FREE_FOR_ORDINARY = frozenset({"free_effect"})
MATERIALS = Literal["wood", "plant", "stone"]


class RequirementV2(ClosedModel):
    id: str = Field(min_length=1, max_length=64)
    quote: str = Field(min_length=1, max_length=1000)
    effect: EffectKind


class EffectIntentV2(ClosedModel):
    kind: EffectKind
    required_by: list[str] = Field(default_factory=list, max_length=16)
    target_id: str | None = Field(default=None, max_length=64)
    source_id: str | None = Field(default=None, max_length=64)
    object_id: str | None = Field(default=None, max_length=64)
    destination_id: str | None = Field(default=None, max_length=32)
    travel_scope: Literal["within_scene", "between_locations"] | None = None
    recipient_id: str | None = Field(default=None, max_length=64)
    effect_id: str | None = Field(default=None, max_length=64)
    label: str = Field(default="", max_length=128)
    appearance: str = Field(default="", max_length=500)
    lifetime: Literal["instant", "timed"] = "instant"
    template: ObjectTemplate = "vessel"
    material: MATERIALS = "wood"
    form: Literal["plant_bush"] = "plant_bush"
    aspect: Literal["general", "sight", "hearing"] = "general"
    capacity_ml: int = Field(default=300, ge=1, le=2000, strict=True)
    amount: Count = Field(default=300, ge=1, le=1_000_000)
    quantity: int = Field(default=1, ge=1, le=10, strict=True)
    resistance_attribute: AbilityKey | None = None
    scale: Scale = "tiny"
    sturdiness: Sturdiness = "ordinary"
    leads_to: str = Field(default="", max_length=128)
    leads_view: str = Field(default="", max_length=300)
    abilities: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def lifetime_supported(self):
        if self.travel_scope and self.kind != "move":
            raise ValueError("Travel scope is only valid for movement")
        if self.travel_scope == "within_scene" and self.destination_id:
            raise ValueError("Within-scene movement cannot change the location")
        if self.leads_to and self.scale not in LEADS_SCALES:
            raise ValueError("Only a large or huge creation can lead to another place")
        return self


class IntroductionV2(ClosedModel):
    ref: str = Field(min_length=1, max_length=48)
    template: ObjectTemplate
    name: str = Field(min_length=1, max_length=128)
    evidence_quote: str = Field(min_length=1, max_length=1000)
    amount: Count = Field(default=1000, ge=1, le=1_000_000)
    awareness: Literal["watching_actor", "unknown"] = "watching_actor"


class AbilityDefinitionV2(ClosedModel):
    schema_version: Literal[2] = 2
    id: str = Field(default="", max_length=128)
    revision: Count = Field(default=1, ge=1)
    name: str = Field(min_length=1, max_length=128)
    source: SourceKind
    delivery: Literal["ordinary", "spell", "innate", "item"] = "spell"
    attribute: AbilityKey = "wis"
    intensity: Literal["light", "normal", "strong"] = "light"
    target_count: int = Field(default=1, ge=1, le=100, strict=True)
    duration_seconds: Count = Field(default=18, ge=1, le=MAX_EFFECT_SECONDS)
    effects: list[EffectIntentV2] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def energy_source(self):
        if self.source == "supernatural" and self.attribute == "con":
            raise ValueError("CON has no supernatural energy pool")
        return self


class IntentV2(ClosedModel):
    schema_version: Literal[2] = 2
    name: str = Field(default="", max_length=128)
    source: SourceKind
    # The model's own reading of the player's words; anything but "ordinary" gets an independent review.
    player_request: Literal["ordinary", "supernatural", "pretend", "unclear"] = "unclear"
    delivery: Literal["ordinary", "spell", "innate", "item"] = "ordinary"
    resolution: ResolutionKind = "check"
    attribute: AbilityKey = "wis"
    intensity: Literal["light", "normal", "strong"] = "normal"
    difficulty: int = Field(default=12, ge=1, le=40, strict=True)
    edge: Literal["normal", "advantage", "disadvantage"] = "normal"
    targets: list[str] = Field(default_factory=list, max_length=100)
    requirements: list[RequirementV2] = Field(default_factory=list, max_length=16)
    effects: list[EffectIntentV2] = Field(min_length=1, max_length=16)
    introductions: list[IntroductionV2] = Field(default_factory=list, max_length=8)
    duration_seconds: Count = Field(default=18, ge=1, le=MAX_EFFECT_SECONDS)
    elapsed_game_seconds: Count = Field(default=6, ge=0, le=3600)
    public_reason: str = Field(default="", max_length=4000)
    reward: RewardIntent | None = None
    check_outcomes: CheckNarration | None = None
    known_profile_id: str | None = Field(default=None, max_length=128)
    known_revision: Count = Field(default=1, ge=1)


class IntentReview(ClosedModel):
    verdict: Literal["pass", "mismatch", "clarify", "unsupported", "forbidden"]
    message: str = Field(default="", max_length=1000)
    covered_requirements: list[str] = Field(default_factory=list, max_length=16)


class ExplorationAction(ClosedModel):
    schema_version: Literal[2] = 2
    actor_id: str
    source_message_id: str
    source_hash: str
    definition: AbilityDefinitionV2
    resolution: ResolutionKind
    attribute: AbilityKey
    difficulty: int = Field(ge=1, le=40, strict=True)
    edge: Literal["normal", "advantage", "disadvantage"] = "normal"
    targets: list[str] = Field(min_length=1, max_length=100)
    operations: list[EffectIntentV2] = Field(min_length=1, max_length=16)
    introductions: list[IntroductionV2] = Field(default_factory=list, max_length=8)
    cost: Count
    elapsed_game_seconds: Count
    check_outcomes: CheckNarration | None = None
    public_reason: str = Field(default="", max_length=4000)
    reward: RewardIntent | None = None


class EffectChange(ClosedModel):
    kind: str
    subject_id: str
    description: str
    data: dict = Field(default_factory=dict)
    private: bool = False


class ExplorationOutcome(ActionOutcome):
    schema_version: Literal[2] = 2
    realized: bool = True
    changes: list[EffectChange] = Field(default_factory=list)
    ability_ref: str | None = None
    elapsed_game_seconds: Count = 0
    game_seconds: Count = 0


def definition_key(definition: AbilityDefinitionV2) -> str:
    data = definition.model_dump(mode="json", exclude={"id", "revision", "name"})
    bindings = {
        "target_id",
        "source_id",
        "object_id",
        "recipient_id",
        "effect_id",
        "label",
        "appearance",
        "required_by",
    }
    meaningful = {
        "cannot_move": {"lifetime", "quantity", "resistance_attribute"},
        "cannot_act": {"lifetime", "quantity", "resistance_attribute"},
        "cannot_target": {"lifetime", "quantity", "resistance_attribute"},
        "create_object": {
            "template",
            "material",
            "capacity_ml",
            "lifetime",
            "quantity",
            "scale",
            "sturdiness",
            "leads_to",
        },
        "free_effect": {"scale", "sturdiness", "label"},  # the words are all the meaning it has
        "change_form": {"form", "quantity"},
        "observe": {"aspect"},
        "fill": {"amount"},
        "pour": {"amount"},
        "consume": {"amount"},
    }
    defaults = {"scale": "tiny", "sturdiness": "ordinary", "leads_to": ""}
    data["effects"] = [
        {
            k: v
            for k, v in effect.model_dump(
                mode="json",
                include={"kind"} | meaningful.get(effect.kind, {"lifetime", "quantity"}),
                exclude=bindings - ({"label"} if effect.kind == "free_effect" else set()),
            ).items()
            if defaults.get(k, object()) != v
        }
        for effect in definition.effects
    ]
    if not any(e.kind in TIMED_KINDS or e.lifetime == "timed" for e in definition.effects):
        data.pop("duration_seconds")
    return "ability2-" + hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def effect_price(effect: EffectIntentV2, definition: AbilityDefinitionV2, level: int) -> int:
    """Energy for one start of this effect, before duration units: a creation costs by its size and strength,
    anything else by the spell's intensity."""
    if effect.kind in {"create_object", "free_effect"}:
        return SCALE_PRICE[effect.scale] * (2 if effect.sturdiness == "sturdy" else 1) * level
    return {"light": 1, "normal": 3, "strong": 12}[definition.intensity] * level


def exploration_cost(definition: AbilityDefinitionV2, level: int) -> int:
    if type(level) is not int or level < 1:
        raise ValueError("Level must be a positive exact integer")
    if definition.source != "supernatural":
        return 0
    total = 0
    has_form = any(effect.kind == "change_form" for effect in definition.effects)
    for effect in definition.effects:
        if effect.kind == "hold_breath":
            continue  # Physical auxiliary action is not a second spell.
        if effect.kind == "camouflage" and has_form:
            continue  # Camouflage of a changed form belongs to that form and is not paid twice.
        timed = effect.kind in TIMED_KINDS or effect.lifetime == "timed"
        duration = (definition.duration_seconds + 5) // 6 if timed else 1
        total += effect_price(effect, definition, level) * duration * effect.quantity
    if not total:  # only auxiliary effects: the spell still costs one start at its intensity
        total = {"light": 1, "normal": 3, "strong": 12}[definition.intensity] * level
    return total * definition.target_count


# Fields of an effect that mean something for each kind; the model fills the rest with plausible filler.
_BINDINGS = frozenset(
    {"kind", "required_by", "target_id", "source_id", "object_id", "recipient_id", "effect_id", "label", "appearance"}
)
_RELEVANT = {
    "move": {"destination_id", "travel_scope"},
    "cannot_move": {"lifetime", "quantity", "resistance_attribute"},
    "cannot_act": {"lifetime", "quantity", "resistance_attribute"},
    "cannot_target": {"lifetime", "quantity", "resistance_attribute"},
    "create_object": {
        "template",
        "material",
        "capacity_ml",
        "lifetime",
        "quantity",
        "scale",
        "sturdiness",
        "leads_to",
        "leads_view",
        "abilities",
    },
    "free_effect": {"scale", "sturdiness", "lifetime"},
    "change_form": {"form", "lifetime", "quantity"},
    "observe": {"aspect", "lifetime"},
    "fill": {"amount"},
    "pour": {"amount"},
    "consume": {"amount"},
}
_LIFETIME_KINDS = TIMED_KINDS | {"cosmetic"}


_SELF_ACTS = frozenset({"move", "place", "observe", "speak", "wait", "take", "hold_breath"})
_NO_RISK = frozenset({"move", "speak", "wait", "hold_breath"})


def _exact_count(value):
    """A whole number as text, however the model wrote it (6, 6.0, "6.0"); None when it is not a whole number."""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return str(int(number)) if number == number.to_integral_value() else None


def _empty(value):
    """A missing value as a model spells it: null, or the word "null" in quotes."""
    return value is None or (isinstance(value, str) and value.strip().lower() in {"null", "none"})


def clean_model_intent(raw):
    """Mend what the model got wrong in its own bookkeeping, so only a real problem of meaning is refused.

    The effect is one flat record with fields for every kind, and a model tends to fill them all (a cup with
    form "vessel", a poured drink with lifetime "permanent"). Fields foreign to the effect's kind are dropped
    and the defaults apply; the identity of an ability is computed from the meaningful fields only, so nothing
    changes in meaning. Slips in the cross references are mended too: a requirement the model forgot to link
    is linked to the effect of its own kind, a repeated requirement id is made unique, a link to nothing is
    dropped. Whether the words are really covered stays for the independent review and the compiler.
    Ordinary self actions discard model target noise; actor-targeted combat retains its targets."""
    if not isinstance(raw, dict):
        return raw
    cleaned = {k: v for k, v in raw.items() if not _empty(v) and k != "targets"}
    targeted = {
        "damage",
        "heal",
        "weapon_attack",
        "cannot_move",
        "cannot_act",
        "cannot_target",
        "check_bonus",
        "defense_bonus",
        "damage_over_time",
        "consume",
    }
    if raw.get("targets") and any(isinstance(e, dict) and e.get("kind") in targeted for e in raw.get("effects") or []):
        cleaned["targets"] = raw["targets"]
    effects = []
    for effect in raw.get("effects") or []:
        if not isinstance(effect, dict):
            effects.append(effect)
            continue
        kind = effect.get("kind")
        keep = _BINDINGS | _RELEVANT.get(kind, {"lifetime", "quantity"} if kind in _LIFETIME_KINDS else set())
        known = set(EffectIntentV2.model_fields)
        if kind == "create_object":
            keep = keep - {"object_id"}  # the new object is this effect's result, not something to point at
            if effect.get("scale") not in LEADS_SCALES:
                keep = keep - {"leads_to", "leads_view"}  # only a large creation can lead somewhere
        if effect.get("lifetime") == "permanent":
            effect = {**effect, "lifetime": "timed"}  # nothing the engine keeps is eternal
        mended = {k: v for k, v in effect.items() if not _empty(v) and (k in keep or k not in known)}
        if str(mended.get("amount", "1")).strip() in {"0", "-0"}:
            mended.pop("amount")  # "nothing" is how a model says it was not given an amount
        effects.append(mended)
    # Where the hero walks, places or looks is the story's business, not a target of the effect.
    for effect in effects:
        if isinstance(effect, dict) and effect.get("kind") in _SELF_ACTS:
            effect.pop("target_id", None)
    claim = cleaned.get("player_request")
    if claim == "pretend":
        cleaned["source"] = "mundane"  # pretending to cast is acting, whatever the model labelled it
    if cleaned.get("source") == "mundane" and claim in {"pretend", "ordinary"}:
        # Pretending or an ordinary act is not magic; a claimed spell keeps its magic for the review to weigh.
        effects = [
            e for e in effects if not (isinstance(e, dict) and e.get("kind") in MAGIC_KINDS - FREE_FOR_ORDINARY)
        ] or ([{"kind": "wait"}] if effects else [])
    if not effects and cleaned.get("source") == "mundane":
        effects = [{"kind": "wait"}]
    if (
        cleaned.get("source") == "mundane"
        and effects
        and all(isinstance(e, dict) and e.get("kind") in _NO_RISK for e in effects)
        and not any(isinstance(e, dict) and e.get("kind") == "move" and e.get("object_id") for e in effects)
    ):
        cleaned["resolution"] = "automatic"  # walking, speaking or waiting has no uncertain outcome to roll for
    for key in ("elapsed_game_seconds", "duration_seconds"):
        if key in cleaned:
            exact = _exact_count(cleaned[key])
            if exact is None:
                cleaned.pop(key)
            else:
                cleaned[key] = exact
    requirements = []
    seen = set()
    for index, requirement in enumerate(cleaned.get("requirements") or []):
        if isinstance(requirement, dict) and requirement.get("id") in seen:
            requirement = {**requirement, "id": f"{requirement['id']}_{index + 1}"}
        if isinstance(requirement, dict):
            seen.add(requirement.get("id"))
        requirements.append(requirement)
    if requirements:
        cleaned["requirements"] = requirements
    valid = {r["id"] for r in requirements if isinstance(r, dict) and r.get("id")}
    for effect in effects:
        if isinstance(effect, dict) and isinstance(effect.get("required_by"), list):
            effect["required_by"] = [x for x in effect["required_by"] if x in valid]
    for requirement in requirements:
        if not isinstance(requirement, dict) or not requirement.get("id"):
            continue
        if any(isinstance(e, dict) and requirement["id"] in (e.get("required_by") or []) for e in effects):
            continue
        match = next((e for e in effects if isinstance(e, dict) and e.get("kind") == requirement.get("effect")), None)
        if match is not None:
            match["required_by"] = [*(match.get("required_by") or []), requirement["id"]]
    if "effects" in raw or effects:
        cleaned["effects"] = effects
    return cleaned


def exploration_capabilities():
    return dict(
        schema_version=2,
        ordinary_effects=sorted(ORDINARY_KINDS | FREE_FOR_ORDINARY),
        supernatural_effects=sorted(MAGIC_KINDS),
        default_action_seconds="6",
        default_effect_seconds=str(DEFAULT_EFFECT_SECONDS),
        every_supernatural_use_costs_energy=True,
        resolutions=["automatic", "check", "attack"],
        enemy_reply_limit=1,
        item_statuses=["common", "rare", "unique", "epic"],
        damage_dice="1d6",
        resistance="d20+M(target_attribute) vs 10+M(source_attribute)",
        forms=["plant_bush"],
        object_templates=["vessel", "wood_source", "water_source", "energy_tonic", "observer"],
    )
