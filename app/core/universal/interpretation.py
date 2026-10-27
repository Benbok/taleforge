"""Shared read-only compilation and validation. Semantic review is separate from dice."""

import hashlib
from dataclasses import dataclass

from sqlalchemy import select

from app.core.campaigns import NotFound
from app.core.universal.definitions import load_definition
from app.core.universal.objects import accessible
from app.core.universal.profiles import load_actor
from app.core.universal.validation import authorize_actor
from app.db.models import Entity, HeroAbility
from app.rules.universal.exploration import (
    FREE_FOR_ORDINARY,
    MAGIC_KINDS,
    ORDINARY_KINDS,
    AbilityDefinitionV2,
    ExplorationAction,
    InsufficientEnergy,
    IntentReview,
    IntentV2,
    definition_key,
    exploration_cost,
)


def needs_intent_review(source, intent, known=False):
    # Keywords only flag risk; independent semantic review interprets negation/pretence.
    return (
        not known
        or intent.source == "supernatural"
        or any(word in source.casefold() for word in ("маг", "каст", "заклин", "превращ", "свет", "колд"))
    )


def is_plain_action(intent, *, crossable=False):
    """The model itself read the request as ordinary and every effect is ordinary: no meaning review is needed.

    Where a structure that leads somewhere stands, a walk that names none is not plain: the player may have
    meant to cross it, and only the review can tell."""
    return (
        intent.player_request == "ordinary"
        and intent.source == "mundane"
        and not intent.introductions
        and all(effect.kind in ORDINARY_KINDS for effect in intent.effects)
        and not (crossable and any(e.kind == "move" and not e.object_id for e in intent.effects))
    )


@dataclass
class ValidatedExploration:
    actor: object
    sheet: object
    resources: object


async def compile_exploration(ctx, intent, requirements_review, public_context):
    intent = IntentV2.model_validate(intent.model_dump())
    review = IntentReview.model_validate(requirements_review.model_dump())
    if review.verdict != "pass":
        raise ValueError(review.message or "Намерение требует уточнения")
    source = public_context["source_text"]
    ids = {r.id for r in intent.requirements}
    if len(ids) != len(intent.requirements) or set(review.covered_requirements) != ids:
        raise ValueError("Проверка не покрыла требования")
    for requirement in intent.requirements:
        if requirement.quote not in source or not any(
            op.kind == requirement.effect and requirement.id in op.required_by for op in intent.effects
        ):
            raise ValueError("Заявленный эффект отсутствует в исполняемых компонентах")
    if any(set(op.required_by) - ids for op in intent.effects):
        raise ValueError("Неизвестное требование")
    evidence = public_context.get("evidence", "")
    if any(i.evidence_quote not in evidence for i in intent.introductions):
        raise ValueError("Предмет или наблюдатель не подтверждён известной обстановкой")
    targets = intent.targets or [ctx.actor_id]
    if intent.introductions:
        from app.core.universal.perception import observer_id
        from app.core.universal.profiles import actor_row

        actor = await actor_row(ctx.session, ctx.campaign_id, ctx.actor_id)
        bindings = {
            f"intro:{spec.ref}": observer_id(ctx.campaign_id, actor.location_id, spec)
            for spec in intent.introductions
            if spec.template == "observer"
        }
        targets = [bindings.get(target, target) for target in targets]
        intent.effects = [
            op.model_copy(update={"target_id": bindings.get(op.target_id, op.target_id)}) for op in intent.effects
        ]
    if any(op.kind == "weapon_attack" for op in intent.effects):
        from app.core.universal.inventory import _owned

        weapon = next(op for op in intent.effects if op.kind == "weapon_attack")
        _, _, state = await _owned(ctx.session, ctx.campaign_id, ctx.actor_id, weapon.object_id or "")
        intent.attribute = state.profile.attribute
    definition = AbilityDefinitionV2(
        name=intent.name or ("Магия" if intent.source == "supernatural" else "Действие"),
        source=intent.source,
        delivery=intent.delivery,
        attribute=intent.attribute,
        intensity=intent.intensity,
        target_count=len(targets),
        duration_seconds=intent.duration_seconds,  # 18 seconds unless the player names another term
        effects=intent.effects,
    )
    definition.id = definition_key(definition)
    # A known reference only carries the name and revision of a learned spell; an ordinary free action ignores it.
    if intent.known_profile_id and intent.source == "supernatural":
        try:
            saved = await load_definition(ctx.session, ctx.campaign_id, intent.known_profile_id, intent.known_revision)
        except NotFound:
            raise ValueError("known_profile_id не принадлежит изученной способности: оставь его пустым") from None
        learned = await ctx.session.scalar(
            select(HeroAbility).where(
                HeroAbility.campaign_id == ctx.campaign_id,
                HeroAbility.character_id == ctx.actor_id,
                HeroAbility.profile_ref == saved.id,
                HeroAbility.profile_revision == saved.revision,
            )
        )
        if learned is None or definition.id != saved.id:
            raise ValueError("Изученное определение изменено: оставь known_profile_id пустым для нового заклинания")
        # Keep this use's bindings, retain the original ability's name and revision.
        definition.name, definition.revision = saved.name, saved.revision
    sheet, _ = await load_actor(ctx.session, ctx.campaign_id, ctx.actor_id)
    action = ExplorationAction(
        actor_id=ctx.actor_id,
        source_message_id=public_context["source_message_id"],
        source_hash=hashlib.sha256(source.encode()).hexdigest(),
        definition=definition,
        resolution=intent.resolution,
        attribute=intent.attribute,
        difficulty=intent.difficulty,
        edge=intent.edge,
        targets=targets,
        operations=intent.effects,
        introductions=intent.introductions,
        cost=exploration_cost(definition, sheet.level),
        elapsed_game_seconds=intent.elapsed_game_seconds,
        check_outcomes=intent.check_outcomes,
        public_reason=intent.public_reason,
        reward=intent.reward,
    )
    await validate_exploration(ctx, action)
    return action


async def validate_exploration(ctx, action):
    a = ExplorationAction.model_validate(action.model_dump())
    actor = await authorize_actor(ctx, a)
    sheet, resources = await load_actor(ctx.session, ctx.campaign_id, a.actor_id)
    if (
        a.definition.id != definition_key(a.definition)
        or a.operations != a.definition.effects
        or a.attribute != a.definition.attribute
        or a.definition.target_count != len(a.targets)
        or a.cost != exploration_cost(a.definition, sheet.level)
    ):
        raise ValueError("Несогласованное определение действия")
    from app.core.universal.combat_actions import COMBAT_KINDS, effective_actor, scoped_targets

    combat = any(op.kind in COMBAT_KINDS or op.kind == "consume" for op in a.operations)
    current = await effective_actor(ctx.session, ctx.campaign_id, a.actor_id, pending_event_id=ctx.pending_event_id)
    passive_wait = (
        a.definition.source == "mundane"
        and a.resolution == "automatic"
        and not a.introductions
        and a.targets == [actor.id]
        and all(op.kind == "wait" for op in a.operations)
    )
    if resources.hp <= 0 or (current["cannot_act"] and not passive_wait):
        raise ValueError("Герой сейчас не может действовать")
    if current["cannot_move"] and any(op.kind == "move" for op in a.operations):
        raise ValueError("Эффект запрещает двигаться")
    if (not combat and a.targets != [ctx.actor_id]) or a.resolution not in {
        "automatic",
        "check",
        "attack",
        "resistance",
    }:
        raise ValueError("Недоступная цель или тип разрешения")
    if combat:
        targets = await scoped_targets(ctx, a)
        if (
            current["cannot_move"]
            and any(op.kind == "weapon_attack" for op in a.operations)
            and any(target.zone == "far" for target in targets.values())
        ):
            raise ValueError("Связанный герой не может приблизиться для удара оружием")
        if current["cannot_target"] and any(
            op.kind in {"damage", "weapon_attack", "cannot_move", "cannot_act", "cannot_target"} for op in a.operations
        ):
            raise ValueError("Эффект запрещает выбирать цель")
        if any(op.kind in {"damage", "weapon_attack"} for op in a.operations) and a.resolution != "attack":
            raise ValueError("Атака требует серверного броска попадания")
    elif a.resolution not in {"automatic", "check"}:
        raise ValueError("Обычное действие не является атакой")
    if a.resolution == "check" and (
        a.check_outcomes is None or any(not value for value in a.check_outcomes.model_dump().values())
    ):
        raise ValueError("Нужны четыре подсказки исходов проверки")
    if a.definition.source == "supernatural":
        have = resources.energies.get(a.attribute, 0)
        if a.cost < 1:
            raise ValueError("Сверхъестественное действие должно иметь положительную цену")
        if have < a.cost:
            raise InsufficientEnergy(a.cost, have)
    elif any(op.kind in MAGIC_KINDS - FREE_FOR_ORDINARY for op in a.operations):
        raise ValueError("Сверхъестественное действие не может быть бесплатным")
    if a.elapsed_game_seconds > 3600 or a.elapsed_game_seconds < 1:
        raise ValueError("Игровое действие требует положительного времени")
    refs = {f"intro:{i.ref}" for i in a.introductions}
    if len(refs) != len(a.introductions):
        raise ValueError("Повтор ссылки на предмет")
    if sum(bool(op.destination_id) for op in a.operations) > 1:
        raise ValueError("За одно действие можно перейти только в одно соседнее место")
    for index, op in enumerate(a.operations):
        if op.travel_scope == "between_locations" and not op.destination_id and not op.object_id:
            raise ValueError("Для перехода нужно известное место назначения")
        if op.destination_id:
            if op.kind != "move":
                raise ValueError("Место назначения допустимо только для перехода")
            from app.core.universal.travel import destination_view

            await destination_view(ctx, op.destination_id, allow_unprepared=True)
        if op.target_id and op.kind != "pour" and op.target_id not in a.targets:
            raise ValueError("Недоступная цель компонента")
        if op.kind == "create_object" and (op.template not in {"vessel", "structure", "creature"} or op.quantity != 1):
            raise ValueError("Создаётся один предмет, одна постройка или одно существо")
        for field in ("source_id", "object_id") + (("target_id",) if op.kind == "pour" else ()):
            ref = getattr(op, field)
            if not ref:
                continue
            if ref in refs:
                continue
            obj = await ctx.session.get(Entity, ref)
            if obj is not None and "universal_item" in obj.state:
                from app.core.universal.inventory import _owned

                # A deed may be done with one's own gear (drawn, or named in what is done); only raw-material uses
                # such as placing, giving or pouring it are refused.
                if op.kind not in {"weapon_attack", "equip", "unequip", "consume", "free_effect", "take"}:
                    raise ValueError("Снаряжение не является обычным материалом")
                _, _, item = await _owned(ctx.session, ctx.campaign_id, a.actor_id, ref)
                if op.kind == "weapon_attack" and (
                    item.profile.kind != "weapon" or not item.equipped or item.profile.attribute != a.attribute
                ):
                    raise ValueError("Нужно надетое оружие и его характеристика")
            else:
                accessible(obj, actor)
        if op.kind == "create_object":
            refs.add(f"created:{index}")
    return ValidatedExploration(actor, sheet, resources)
