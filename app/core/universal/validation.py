"""The same executable capability/scope/budget checks run before save and inside execution."""

from dataclasses import dataclass

from sqlalchemy import func, select

from app.core.campaigns import NotFound
from app.core.universal.contracts import ProposedAction
from app.core.universal.profiles import actor_row, get_profile, load_actor
from app.db.models import Character, HeroAbility, RuntimeProfile, Seat
from app.rules.universal.failures import reject
from app.rules.universal.profiles import bind_resistance, resource_cost, validate_profile


def capabilities():
    return dict(
        version=1,
        action_kinds=["narrative", "ordinary_check", "ability", "weapon_attack", "world_denial", "unsupported"],
        effect_kinds=[
            "check",
            "damage",
            "heal",
            "cannot_act",
            "cannot_move",
            "cannot_target",
            "check_bonus",
            "defense_bonus",
        ],
        profile_kinds=["check", "damage", "heal", "control", "defense"],
        clocks=["immediate"],
        max_duration=1,
        target_scopes=["self", "actors"],
        ordinary_checks_cost=0,
        item_profiles=False,
        conditions=False,
        scene_effects=False,
        rarity="common",
        dice=["1d4", "1d6"],
    )


async def authorize_actor(ctx, proposal, *, require_active=True):
    if getattr(ctx, "npc_reply", False):
        from app.core.universal.combat import authorize_enemy

        return await authorize_enemy(ctx, proposal, require_active=require_active)
    try:
        row = await actor_row(ctx.session, ctx.campaign_id, proposal.actor_id, refresh=True)
    except NotFound:
        reject("not_allowed")
    seat = await ctx.session.get(Seat, ctx.seat_id, populate_existing=True)
    if (
        proposal.actor_id != ctx.actor_id
        or not isinstance(row, Character)
        or row.seat_id != ctx.seat_id
        or seat is None
        or seat.campaign_id != ctx.campaign_id
        or ctx.user_id not in {seat.user_id, seat.stand_in_user_id}
        or require_active
        and row.status not in {"active", "approved"}
    ):
        reject("not_allowed")
    return row


@dataclass
class ActionState:
    row: object
    sheet: object
    resources: object
    profile: object
    targets: dict
    effects: list
    cost: int
    energy: str | None


async def validate_action(ctx, proposal, *, require_saved_profile=True):
    try:
        p = ProposedAction.model_validate(proposal.model_dump())
        profile = validate_profile(p.profile)
    except ValueError:
        reject("invalid_proposal")
    s = ctx.session
    row = await authorize_actor(ctx, p)
    if profile.id != p.ref.profile_id or profile.revision != p.ref.revision or p.operations != profile.effects:
        reject("invalid_proposal")
    saved_row = await s.get(RuntimeProfile, (ctx.campaign_id, profile.id, profile.revision))
    if require_saved_profile or saved_row is not None:
        try:
            saved = await get_profile(s, ctx.campaign_id, p.ref.profile_id, p.ref.revision)
        except NotFound:
            reject("stale_profile")
        latest = await s.scalar(
            select(func.max(RuntimeProfile.revision)).where(
                RuntimeProfile.campaign_id == ctx.campaign_id, RuntimeProfile.ref == profile.id
            )
        )
        learned = await s.scalar(
            select(HeroAbility).where(
                HeroAbility.campaign_id == ctx.campaign_id,
                HeroAbility.character_id == p.actor_id,
                HeroAbility.profile_ref == profile.id,
                HeroAbility.profile_revision == profile.revision,
            )
        )
        pinned = learned is not None and learned.definition == profile.model_dump(mode="json")
        if saved != profile or latest != profile.revision and not pinned:
            reject("stale_profile")
    policy = capabilities()
    if profile.duration > policy["max_duration"] or any(e.clock not in policy["clocks"] for e in profile.effects):
        reject("unsupported_duration")
    if (
        profile.item_id is not None
        and not policy["item_profiles"]
        or profile.use_conditions
        and not policy["conditions"]
    ):
        reject("unsupported_item")
    if profile.kind not in policy["profile_kinds"]:
        reject("unsupported_profile")
    sheet, resources = await load_actor(s, ctx.campaign_id, p.actor_id)
    if profile.trained and profile.id not in sheet.trained:
        reject("invalid_proposal")
    if profile.resource_key is not None and profile.resource_key != profile.attribute:
        reject("invalid_proposal")
    if profile.use_kind == "weapon_basic":
        weapon = sheet.starting_equipment.weapon if sheet.starting_equipment else None
        if weapon is None or profile.attribute != weapon.attack_ability or profile.base_dice != weapon.damage_dice:
            reject("invalid_proposal")
    if not p.targets or len(p.targets) != len(set(p.targets)) or len(p.targets) != profile.target_count:
        reject("invalid_targets")
    targets = {}
    for target in p.targets:
        if ctx.allowed_target_ids is not None and target not in ctx.allowed_target_ids and target != p.actor_id:
            reject("target_unavailable")
        try:
            target_row = await actor_row(s, ctx.campaign_id, target, refresh=True)
            if target_row.location_id != row.location_id:
                reject("target_unavailable")
            targets[target] = await load_actor(s, ctx.campaign_id, target)
        except (NotFound, ValueError) as exc:
            from app.rules.universal.failures import ActionValidationError

            if isinstance(exc, ActionValidationError):
                raise
            reject("target_unavailable")
    cost = resource_cost(profile, sheet.level)
    energy = profile.resource_key or (profile.attribute if profile.attribute != "con" else None)
    if cost and (energy is None or resources.energies[energy] < cost):
        reject("insufficient_resources")
    effects = []
    for effect in profile.effects:
        if (
            effect.source_id
            and effect.source_id != p.actor_id
            or effect.target_id
            and effect.target_id not in p.targets
        ):
            reject("invalid_targets")
        resistance = (
            bind_resistance(effect.resistance, getattr(sheet.abilities, effect.resistance.source_attribute))
            if effect.resistance
            else None
        )
        effects.append(effect.model_copy(update={"resistance": resistance}))
    if p.actor_id in targets:
        targets[p.actor_id] = (sheet, resources)
    return ActionState(row, sheet, resources, profile, targets, effects, cost, energy)
