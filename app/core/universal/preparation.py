"""Compile semantic intent into bounded server rules, validate, then save immutable profiles."""

import hashlib
import json

from pydantic import Field
from sqlalchemy import select

from app.core.universal.action_intents import ActionCategory, ActionIntent, LegacyAdmission
from app.core.universal.contracts import ActionRef, ProposedAction
from app.core.universal.profiles import get_profile, load_actor, put_profile
from app.core.universal.validation import validate_action
from app.db.models import HeroAbility
from app.rules.universal.contracts import ClosedModel
from app.rules.universal.failures import ActionFailure, action_failure, reject
from app.rules.universal.profiles import EffectSpec, ProfileSpec, ResistanceSpec


class PreparedAction(ClosedModel):
    version: int = 1
    category: ActionCategory
    public_reason: str = ""
    proposal: ProposedAction | None = None
    failure: ActionFailure | None = None
    name: str = Field(default="", max_length=128)


def _effect(kind, index, attribute, intensity, resistance_attribute=None):
    if kind in {"check", "narrative"}:
        reject("unsupported_profile")
    value = {"light": 1, "normal": 2, "strong": 3}[intensity] if kind in {"check_bonus", "defense_bonus"} else 0
    resistance = (
        ResistanceSpec(source_attribute=attribute, attribute=resistance_attribute) if resistance_attribute else None
    )
    return EffectSpec(id=f"component-{index}", kind=kind, value=value, resistance=resistance)


def _compile_profile(intent: ActionIntent, source_id, sheet):
    if intent.duration != 1 or intent.clock != "immediate":
        reject("unsupported_duration")
    if intent.target_scope == "scene" or intent.effect == "narrative" and intent.kind == "ability":
        reject("unsupported_profile")
    if intent.kind == "ordinary_check":
        if intent.effect != "check" or intent.extra_effects or intent.intensity != "normal":
            reject("invalid_proposal")
        return ProfileSpec(id="check-" + source_id, kind="check", attribute=intent.attribute)
    if intent.kind == "weapon_attack":
        if intent.extra_effects or intent.intensity != "normal":
            reject("invalid_proposal")
        weapon = sheet.starting_equipment.weapon if sheet.starting_equipment else None
        if weapon is None:
            reject("invalid_proposal")
        return ProfileSpec(
            id="weapon-" + source_id,
            kind="damage",
            use_kind="weapon_basic",
            attribute=weapon.attack_ability,
            base_dice=weapon.damage_dice,
        )
    if intent.attribute == "con":
        reject("invalid_proposal")
    if intent.base_dice == "1d8":
        reject("unsupported_item")
    kind = intent.effect
    effects = []
    if kind in {"cannot_act", "cannot_move", "cannot_target"}:
        effects.append(_effect(kind, 0, intent.attribute, intent.intensity))
        kind = "control"
    elif kind in {"check_bonus", "defense_bonus"}:
        effects.append(_effect(kind, 0, intent.attribute, intent.intensity))
        kind = "defense"
    for extra in intent.extra_effects:
        effects.append(
            _effect(extra.kind, len(effects), intent.attribute, intent.intensity, extra.resistance_attribute)
        )
    p = ProfileSpec(
        id="pending",
        kind=kind,
        attribute=intent.attribute,
        base_dice=intent.base_dice,
        resource_key=intent.attribute,
        intensity=intent.intensity,
        target_count=len(intent.targets) or 1,
        effects=effects,
    )
    identity = p.model_dump(mode="json", exclude={"id", "revision"})
    ref = "ability-" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    return p.model_copy(update={"id": ref})


async def prepare_action(ctx, intent, source_id):
    s = ctx.session
    public_reason = intent.public_reason
    category = intent.kind
    if category in {"world_denial", "denied"}:
        failure = ActionFailure(
            category="world_denial",
            code="world_denial",
            message=public_reason or "Действие невозможно по установленным законам мира.",
        )
        return PreparedAction(category="world_denial", public_reason=failure.message, failure=failure)
    if category == "unsupported":
        failure = action_failure("unsupported_profile")
        return PreparedAction(category="unsupported", public_reason=failure.message, failure=failure)
    if category == "narrative":
        if isinstance(intent, ActionIntent) and (
            intent.extra_effects
            or intent.targets
            or intent.effect != "check"
            or intent.duration != 1
            or intent.clock != "immediate"
            or intent.target_scope != "self"
        ):
            reject("invalid_proposal")
        return PreparedAction(category="narrative", public_reason=public_reason)
    sheet, _ = await load_actor(s, ctx.campaign_id, ctx.actor_id)
    known = list(
        await s.scalars(
            select(HeroAbility).where(
                HeroAbility.campaign_id == ctx.campaign_id, HeroAbility.character_id == ctx.actor_id
            )
        )
    )
    if intent.known_profile_id:
        learned = next(
            (
                a
                for a in known
                if a.profile_ref == intent.known_profile_id and a.profile_revision == intent.known_revision
            ),
            None,
        )
        if learned is None:
            reject("not_allowed")
        profile = await get_profile(s, ctx.campaign_id, learned.profile_ref, learned.profile_revision)
    elif isinstance(intent, LegacyAdmission):
        profile = (
            ProfileSpec(id="check-" + source_id, attribute=intent.attribute, kind="check")
            if category == "check"
            else intent.profile
        )
        if profile is None:
            reject("invalid_proposal")
    else:
        profile = _compile_profile(intent, source_id, sheet)
    # Canonical category comes from compiled rules, never an outer model label.
    category = (
        "weapon_attack"
        if profile.use_kind == "weapon_basic"
        else ("ordinary_check" if profile.kind == "check" and profile.resource_key is None else "ability")
    )
    candidate = profile.model_dump(exclude={"id", "revision"})
    for learned in known:
        saved = ProfileSpec.model_validate(learned.definition)
        if saved.model_dump(exclude={"id", "revision"}) == candidate:
            profile = saved
            break
    proposal = ProposedAction(
        ref=ActionRef(profile_id=profile.id, revision=profile.revision),
        actor_id=ctx.actor_id,
        targets=intent.targets or [ctx.actor_id],
        profile=profile,
        operations=profile.effects,
        reason=public_reason or (intent.name if isinstance(intent, ActionIntent) else "") or source_id,
        difficulty=intent.difficulty,
    )
    await validate_action(ctx, proposal, require_saved_profile=False)
    await put_profile(s, ctx.campaign_id, profile)
    return PreparedAction(
        category=category,
        proposal=proposal,
        public_reason=public_reason,
        name=intent.name if isinstance(intent, ActionIntent) else "",
    )
