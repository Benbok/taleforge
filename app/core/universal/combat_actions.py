"""Actual combat primitives shared by hero actions and saved enemy replies."""

from sqlalchemy import select

from app.core.universal.effects import EFFECT_LABELS, active_effects, start_effect
from app.core.universal.inventory import _owned, actor_derived, ensure_inventory, equip
from app.core.universal.profiles import actor_row, load_actor, save_actor
from app.db.models import Character, Entity, UniversalEffect
from app.rules.universal.exploration import EffectChange
from app.rules.universal.items import item_attack_profile
from app.rules.universal.profiles import CheckProof, EffectOutcome, ProfileSpec, damage_amount, resolve_check

COMBAT_KINDS = frozenset(
    {
        "damage",
        "heal",
        "cannot_move",
        "cannot_act",
        "cannot_target",
        "check_bonus",
        "defense_bonus",
        "weapon_attack",
        "guard",
        "equip",
        "unequip",
        "damage_over_time",
    }
)
CONTROL_KINDS = frozenset({"cannot_move", "cannot_act", "cannot_target"})


async def effective_actor(session, campaign_id, actor_id, *, at_seconds=None, pending_event_id=None):
    derived = await actor_derived(session, campaign_id, actor_id)
    effects = await active_effects(session, campaign_id, actor_id, at_seconds=at_seconds)
    if pending_event_id:
        existing = {e["id"] for e in effects}
        for row in await session.scalars(
            select(UniversalEffect).where(
                UniversalEffect.campaign_id == campaign_id,
                UniversalEffect.target_id == actor_id,
                UniversalEffect.source_event_id == pending_event_id,
                UniversalEffect.status == "active",
            )
        ):
            if row.id not in existing:
                effects.append(dict(id=row.id, kind=row.definition["kind"], definition=row.definition))
    kinds = {e["kind"] for e in effects}
    defense = sum(
        e["definition"].get("context", {}).get("bonus", 0) for e in effects if e["kind"] in {"defense_bonus", "guard"}
    )
    check_bonus = sum(e["definition"].get("context", {}).get("bonus", 0) for e in effects if e["kind"] == "check_bonus")
    return dict(
        derived=derived.model_copy(update={"ac": derived.ac + defense}),
        effects=effects,
        cannot_move="cannot_move" in kinds or "change_form" in kinds,
        cannot_act="cannot_act" in kinds,
        cannot_target="cannot_target" in kinds,
        check_bonus=check_bonus,
    )


async def scoped_targets(ctx, action):
    actor = await actor_row(ctx.session, ctx.campaign_id, action.actor_id)
    targets = {}
    from app.core.universal.perception import observer_id

    introductions = {
        observer_id(ctx.campaign_id, actor.location_id, spec): spec
        for spec in action.introductions
        if spec.template == "observer"
    }
    if len(action.targets) != len(set(action.targets)):
        raise ValueError("Повтор цели")
    for target_id in action.targets:
        if (
            ctx.allowed_target_ids is not None
            and target_id != actor.id
            and target_id not in ctx.allowed_target_ids
            and target_id not in introductions
        ):
            raise ValueError("Цель не видна герою")
        if target_id in introductions and await ctx.session.get(Entity, target_id) is None:
            spec = introductions[target_id]
            target = Entity(
                id=target_id,
                campaign_id=ctx.campaign_id,
                kind="creature",
                name=spec.name,
                location_id=actor.location_id,
                state={},
            )
        else:
            target = await actor_row(ctx.session, ctx.campaign_id, target_id, refresh=True)
        from app.core.universal.visibility import visible_entity

        if target.location_id != actor.location_id or (
            isinstance(target, Entity) and not await visible_entity(ctx.session, ctx.campaign_id, ctx.actor_id, target)
        ):
            raise ValueError("Цель недоступна")
        if isinstance(target, Character) or target.state.get("universal_sheet"):
            _, target_resources = await load_actor(ctx.session, ctx.campaign_id, target_id)
            if target_resources.hp <= 0 and any(
                op.kind in {"damage", "weapon_attack", "cannot_move", "cannot_act", "cannot_target"}
                for op in action.operations
            ):
                raise ValueError("Недействующая цель не может быть атакована этим действием")
        elif target.kind != "creature":
            raise ValueError("Цель не является участником боя")
        targets[target_id] = target
    return targets


async def initialize_combatant(session, campaign_id, actor_id):
    from app.rules.universal.contracts import UniversalSheet
    from app.rules.universal.mechanics import derive

    actor = await actor_row(session, campaign_id, actor_id)
    if isinstance(actor, Character) or actor.state.get("universal_sheet"):
        return
    if actor.kind != "creature":
        raise ValueError("Это не существо")
    sheet = UniversalSheet(
        abilities=dict(str=13, dex=12, con=10, int=8, wis=10, cha=8),
        description={"identity": actor.description or actor.name},
    )
    derived = derive(sheet, [])
    actor.state = {
        **actor.state,
        "universal_sheet": sheet.model_dump(mode="json"),
        "resources": dict(hp=str(derived.hp_max), energies={k: str(v) for k, v in derived.energy_max.items()}),
    }
    await session.flush()


async def combat_action(ctx, action, event, result, now):
    from app.core.universal.resolution import _RecordingDice

    s = ctx.session
    await ensure_inventory(s, ctx.campaign_id, action.actor_id)
    sheet, _ = await load_actor(s, ctx.campaign_id, action.actor_id)
    targets = await scoped_targets(ctx, action)
    dice = _RecordingDice(ctx.dice)
    attacker_state = await effective_actor(s, ctx.campaign_id, action.actor_id, pending_event_id=ctx.pending_event_id)
    all_hits = []
    for target_id, target in targets.items():
        await initialize_combatant(s, ctx.campaign_id, target_id)
        hit = True
        critical = False
        damaging = any(
            op.kind in {"damage", "weapon_attack"} and op.target_id in {None, target_id} for op in action.operations
        )
        weapon = next((op for op in action.operations if op.kind == "weapon_attack"), None)
        profile = ProfileSpec(
            id="numeric", kind="damage", attribute=action.attribute, intensity=action.definition.intensity
        )
        if weapon:
            _, row, item = await _owned(s, ctx.campaign_id, action.actor_id, weapon.object_id or "")
            profile = item_attack_profile(item.profile, row.id)
        if damaging and action.resolution == "attack":
            if isinstance(target, Entity):
                target.state = {**target.state, "hostile": True}
            target_state = await effective_actor(s, ctx.campaign_id, target_id, pending_event_id=ctx.pending_event_id)
            difficulty = target_state["derived"].ac
            check = resolve_check(
                dice,
                getattr(sheet.abilities, action.attribute),
                False,
                difficulty - profile.attack_bonus - attacker_state["check_bonus"],
                action.edge,
            )
            hit, critical = check.success, check.critical
            all_hits.append(hit)
            result.critical |= check.critical
            result.critical_failure |= check.critical_failure
            result.natural, result.total = (
                check.natural,
                check.total + profile.attack_bonus + attacker_state["check_bonus"],
            )
            result.checks.append(
                CheckProof(
                    target_id=target_id,
                    attribute=action.attribute,
                    natural=check.natural,
                    total=result.total,
                    modifier=result.total - check.natural,
                    difficulty=difficulty,
                    success=hit,
                    kind="attack",
                    mode=action.edge,
                    critical=check.critical,
                    critical_failure=check.critical_failure,
                )
            )
            if check.critical_failure:
                own_sheet, own_resources = await load_actor(s, ctx.campaign_id, action.actor_id)
                own_resources.hp = max(0, own_resources.hp - 1)
                await save_actor(s, ctx.campaign_id, action.actor_id, own_sheet, own_resources)
                await synchronize_vitality(ctx, action.actor_id, event.id)
                result.changes.append(
                    EffectChange(
                        kind="damage",
                        subject_id=action.actor_id,
                        description="Оружие срывается: герой теряет 1 HP.",
                        data={"amount": "1"},
                    )
                )
        for index, op in enumerate(action.operations):
            if op.kind not in COMBAT_KINDS or op.target_id not in {None, target_id}:
                continue
            if op.kind in {"equip", "unequip"}:
                await equip(
                    s,
                    ctx.campaign_id,
                    action.actor_id,
                    op.object_id or "",
                    op.kind == "equip",
                    f"gear-{event.id}-{index}",
                )
                result.changes.append(
                    EffectChange(kind=op.kind, subject_id=action.actor_id, description="Экипировка изменена.")
                )
                continue
            if not hit:
                continue
            if op.kind in {"damage", "weapon_attack", "heal"}:
                amount = damage_amount(dice, sheet, profile, critical)
                target_sheet, resources = await load_actor(s, ctx.campaign_id, target_id)
                before = resources.hp
                if op.kind == "heal":
                    if (target.resources if isinstance(target, Character) else target.state.get("resources", {})).get(
                        "vitality", {}
                    ).get("state") == "dead":
                        raise ValueError("Погибшего нельзя вылечить")
                    resources.hp = min((await actor_derived(s, ctx.campaign_id, target_id)).hp_max, before + amount)
                else:
                    resources.hp = max(0, before - amount)
                    result.damage += before - resources.hp
                    if isinstance(target, Entity):
                        target.state = {**target.state, "hostile": True}
                await save_actor(s, ctx.campaign_id, target_id, target_sheet, resources)
                if resources.hp == before:
                    result.realized = False
                await synchronize_vitality(
                    ctx,
                    target_id,
                    event.id,
                    before_hp=before,
                    incoming=amount if op.kind != "heal" else 0,
                    critical=critical,
                )
                change_word = "восстановлено" if op.kind == "heal" else "потеряно"
                result.changes.append(
                    EffectChange(
                        kind="heal" if op.kind == "heal" else "damage",
                        subject_id=target_id,
                        description=f"{target.name}: {change_word} {abs(resources.hp - before)} HP.",
                        data=dict(amount=str(abs(resources.hp - before))),
                    )
                )
            else:
                applied = True
                if op.kind in CONTROL_KINDS:
                    target_sheet, _ = await load_actor(s, ctx.campaign_id, target_id)
                    attribute = op.resistance_attribute or ("dex" if op.kind == "cannot_move" else "wis")
                    difficulty = 10 + (getattr(sheet.abilities, action.attribute) - 10) // 2
                    check = resolve_check(dice, getattr(target_sheet.abilities, attribute), False, difficulty)
                    applied = not check.success
                    result.effect_outcomes.append(
                        EffectOutcome(
                            effect_id=str(index),
                            target_id=target_id,
                            natural=check.natural,
                            total=check.total,
                            difficulty=difficulty,
                            applied=applied,
                        )
                    )
                    result.checks.append(
                        CheckProof(
                            target_id=target_id,
                            effect_id=str(index),
                            attribute=attribute,
                            natural=check.natural,
                            total=check.total,
                            modifier=check.total - check.natural,
                            difficulty=difficulty,
                            success=check.success,
                            kind="resistance",
                            critical=check.critical,
                            critical_failure=check.critical_failure,
                        )
                    )
                if applied:
                    bonus = (
                        2 if op.kind == "guard" else {"light": 1, "normal": 2, "strong": 3}[action.definition.intensity]
                    )
                    duration = action.definition.duration_seconds if op.kind != "guard" else 6
                    await start_effect(
                        s,
                        ctx.campaign_id,
                        action.actor_id,
                        target_id,
                        event.id,
                        str(index),
                        op,
                        now + action.elapsed_game_seconds,
                        duration,
                        context=dict(
                            bonus=bonus if op.kind in {"guard", "check_bonus", "defense_bonus"} else 0,
                            periodic=op.kind == "damage_over_time",
                            intensity=action.definition.intensity,
                            attribute=action.attribute,
                            source_sheet=sheet.model_dump(mode="json"),
                        ),
                    )
                    result.changes.append(
                        EffectChange(
                            kind=op.kind,
                            subject_id=target_id,
                            description=(
                                f"{target.name}: эффект «{op.label or EFFECT_LABELS.get(op.kind, 'Эффект')}» "
                                f"действует {duration} с."
                            ),
                        )
                    )
    if all_hits:
        result.success = any(all_hits)
        result.realized &= all(all_hits)
    result.rolls.extend(dice.rolls)
    result.draws.extend(dice.draws)


async def synchronize_vitality(ctx, actor_id, source_key, *, before_hp=None, incoming=0, critical=False):
    from app.core.universal.clock import clock_view
    from app.core.universal.vitality import enter_zero_hp
    from app.db.models import CombatExchange

    exchange = await ctx.session.get(CombatExchange, ctx.exchange_id) if ctx.exchange_id else None
    sequence = (
        int(exchange.sequence) if exchange else int((await clock_view(ctx.session, ctx.campaign_id))["step_index"]) + 1
    )
    await enter_zero_hp(ctx.session, ctx.campaign_id, actor_id, source_key, sequence)
    if before_hp == 0 and incoming > 0:
        from app.core.universal.vitality import harm_unconscious

        await harm_unconscious(ctx.session, ctx.campaign_id, actor_id, source_key, sequence, critical=critical)
