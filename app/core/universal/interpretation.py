"""Shared read-only compilation and validation. Semantic review is separate from dice."""

import hashlib
import logging
from dataclasses import dataclass

from sqlalchemy import select

from app.core.campaigns import AccessDenied, NotFound
from app.core.universal.attempts import approach_closed
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
    energy_attribute,
    exploration_cost,
)
from app.rules.universal.failures import ActionValidationError

log = logging.getLogger(__name__)
IMPOSSIBLE_MARGIN = 5
TOOL_DISCOUNT = 2  # a real tool in hand
METHOD_DISCOUNT = 2  # a concrete way, as the review confirms
MIN_DIFFICULTY = 5
_QUOTE_MARKS = str.maketrans({c: '"' for c in "«»„“”'"})


def normalize_quote(text):
    """Quotes are checked against the player's words by meaning of the letters, not by typography: case, ё/е,
    quote marks and runs of whitespace never make a quote 'not verbatim'."""
    return " ".join(text.casefold().replace("ё", "е").translate(_QUOTE_MARKS).split())


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
        and not intent.concrete_method  # a discount for the way needs the independent review to confirm it
        and intent.source == "mundane"
        and not intent.introductions
        and all(effect.kind in ORDINARY_KINDS for effect in intent.effects)
        and not (crossable and any(e.kind == "move" and not e.object_id for e in intent.effects))
    )


def _leads_somewhere(row):
    from app.core.universal.objects import object_state

    if "exploration" not in (row.state or {}):
        return False  # a scene prop without exploration state cannot be crossed either
    state = object_state(row)
    return state.template == "structure" and bool(state.leads_to)


async def usable_tool(ctx, item_id):
    """The id of a tool the hero really has (their own item, or an object at hand), else None: a made-up or
    foreign tool gives no discount and is no reason to refuse the deed."""
    if not item_id:
        return None
    from app.core.universal.inventory import owned_items
    from app.core.universal.profiles import actor_row

    if any(row.id == item_id for row in await owned_items(ctx.session, ctx.campaign_id, ctx.actor_id)):
        return item_id
    row = await ctx.session.get(Entity, item_id)
    if row is not None and "exploration" in (row.state or {}):
        try:
            accessible(row, await actor_row(ctx.session, ctx.campaign_id, ctx.actor_id))
            return item_id
        except AccessDenied:
            pass
    log.info("tool %s is not the hero's to use: no discount", item_id)
    return None


async def scene_targets(ctx):
    """The hero's place id and every id a check there may aim at: the place, beings and things in it, open ways."""
    from app.core.universal.profiles import actor_row

    actor = await actor_row(ctx.session, ctx.campaign_id, ctx.actor_id)
    ids = {actor.location_id} if actor.location_id else set()
    if actor.location_id:
        ids.update(
            await ctx.session.scalars(
                select(Entity.id).where(Entity.campaign_id == ctx.campaign_id, Entity.location_id == actor.location_id)
            )
        )
        place = await ctx.session.get(Entity, actor.location_id)
        state = (place.state if place else None) or {}
        for link in [*(state.get("links") or []), *((state.get("sketch") or {}).get("exits") or [])]:
            if isinstance(link, dict) and link.get("universal_passage") and not link.get("hidden"):
                ids.add(link["universal_passage"])
    return actor.location_id, ids


async def nothing_hidden_here(ctx):
    """True when the hero's place holds nothing a search could find: no hidden being or object, no hidden way."""
    from app.core.universal.profiles import actor_row

    actor = await actor_row(ctx.session, ctx.campaign_id, ctx.actor_id)
    place = await ctx.session.get(Entity, actor.location_id) if actor.location_id else None
    for row in await ctx.session.scalars(
        select(Entity).where(Entity.campaign_id == ctx.campaign_id, Entity.location_id == actor.location_id)
    ):
        if (row.state or {}).get("hidden"):
            return False
    state = (place.state if place else None) or {}
    links = [*(state.get("links") or []), *((state.get("sketch") or {}).get("exits") or [])]
    return not any(isinstance(link, dict) and link.get("hidden") for link in links)


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
    if public_context.get("world_development"):
        exits = {exit["id"] for exit in public_context.get("known_exits", [])}
        for op in intent.effects:
            if op.kind != "move":
                continue
            if not op.object_id and op.travel_scope is None:
                raise ValueError(
                    "Укажи travel_scope: between_locations для перехода или within_scene для подхода внутри места"
                )
            if op.destination_id and op.destination_id not in exits:
                raise ValueError("destination_id отсутствует в known_exits; выбери известный выход из known_exits")
    for index, op in enumerate(intent.effects):
        if op.kind != "move" or not op.object_id:
            continue
        crossing = await ctx.session.get(Entity, op.object_id)
        # Only a structure that leads somewhere can be walked over; found out here the model can still repair it,
        # at execution it would be a bare denial of the whole action ("get to the wagon and take the rope").
        if crossing is not None and crossing.kind == "object" and not _leads_somewhere(crossing):
            if op.travel_scope == "within_scene":
                # The model named the thing it walks up to: that is an approach, not a crossing.
                intent.effects[index] = op.model_copy(update={"object_id": None})
                continue
            raise ValueError(
                f"«{crossing.name}» никуда не ведёт: move с object_id нужен только для моста, лестницы или прохода. "
                "Чтобы подойти к предмету внутри места, используй move без object_id и travel_scope=within_scene"
            )
    ids = {r.id for r in intent.requirements}
    if len(ids) != len(intent.requirements) or set(review.covered_requirements) != ids:
        raise ValueError("Проверка не покрыла требования")
    for requirement in intent.requirements:
        # The text goes back to the model as its only hint: it names the cause and the player's own words.
        if normalize_quote(requirement.quote) not in normalize_quote(source):
            raise ValueError(
                f"Цитата требования {requirement.id} должна быть дословным фрагментом слов игрока «{source[:300]}»; "
                "рассказ мастера и история не источник цитат. Переписывай замысел по этим словам."
            )
        if not any(op.kind == requirement.effect and requirement.id in op.required_by for op in intent.effects):
            # The model wrote the effect and forgot the link: the link is the only thing missing, so make it.
            for index, op in enumerate(intent.effects):
                if op.kind == requirement.effect:
                    intent.effects[index] = op.model_copy(update={"required_by": [*op.required_by, requirement.id]})
                    break
        if not any(op.kind == requirement.effect and requirement.id in op.required_by for op in intent.effects):
            raise ValueError(
                f"Для требования {requirement.id} (effect={requirement.effect}) нет эффекта такого вида в effects "
                f"с required_by=[{requirement.id!r}]. Добавь его или замени effect в требовании."
            )
    if any(set(op.required_by) - ids for op in intent.effects):
        raise ValueError("Неизвестное требование")
    evidence = public_context.get("evidence", "")
    if any(normalize_quote(i.evidence_quote) not in normalize_quote(evidence) for i in intent.introductions):
        raise ValueError(
            "Предмет или наблюдатель не подтверждён известной обстановкой; "
            "возьми дословную evidence_quote из established_evidence или убери introduction"
        )
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
        if weapon.object_id:
            _, _, state = await _owned(ctx.session, ctx.campaign_id, ctx.actor_id, weapon.object_id)
            intent.attribute = state.profile.attribute
        else:
            intent.attribute = "str"  # a blow with the fists is the body's strength
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
    sheet, resources = await load_actor(ctx.session, ctx.campaign_id, ctx.actor_id)
    if (
        intent.resolution == "check"
        and intent.effects
        and intent.attribute == "wis"  # perception; working a mechanism out (int) is an obstacle of its own
        and all(op.kind == "observe" and not (op.object_id or op.target_id) for op in intent.effects)
        and await nothing_hidden_here(ctx)
    ):
        # Looking at what is in plain sight has no obstacle and no stake: there is nothing to roll for.
        intent = intent.model_copy(update={"resolution": "automatic"})
    tool_item_id = None
    if intent.resolution == "check":
        tool_item_id = await usable_tool(ctx, intent.tool_item_id)
        discount = (TOOL_DISCOUNT if tool_item_id else 0) + (METHOD_DISCOUNT if intent.concrete_method else 0)
        if discount:
            intent = intent.model_copy(update={"difficulty": max(MIN_DIFFICULTY, intent.difficulty - discount)})
    check_target = None
    if intent.resolution == "check":
        here, known = await scene_targets(ctx)
        check_target = intent.check_target or here
        if check_target is not None and check_target not in known:
            raise ValueError(
                f"check_target «{check_target}» нет в этой сцене: укажи id существа, предмета или прохода отсюда "
                "либо оставь поле пустым (тогда целью будет само место)"
            )
    cost = exploration_cost(definition, sheet.level, intent.difficulty, intent.resolution)
    edge = intent.edge
    have = resources.energies.get(energy_attribute(definition), 0)
    if definition.source != "supernatural" and intent.resolution == "check" and cost > have:
        # An ordinary try is never refused for tiredness: the hero spends what is left and tries at a disadvantage.
        cost, edge = have, "disadvantage"
    action = ExplorationAction(
        actor_id=ctx.actor_id,
        source_message_id=public_context["source_message_id"],
        source_hash=hashlib.sha256(source.encode()).hexdigest(),
        definition=definition,
        resolution=intent.resolution,
        attribute=intent.attribute,
        difficulty=intent.difficulty,
        edge=edge,
        targets=targets,
        check_target=check_target,
        tool_item_id=tool_item_id,
        fumble=intent.fumble,
        operations=intent.effects,
        introductions=intent.introductions,
        cost=cost,
        elapsed_game_seconds=intent.elapsed_game_seconds,
        check_outcomes=intent.check_outcomes,
        public_reason=intent.public_reason,
        reward=intent.reward,
    )
    await validate_exploration(ctx, action)
    return action


def _fair_cost(action, price):
    """The full price, or for a tired hero's ordinary try what was left, which the server marks by a disadvantage."""
    if action.cost == price:
        return True
    return (
        action.definition.source != "supernatural"
        and action.resolution == "check"
        and action.edge == "disadvantage"
        and 0 <= action.cost < price
    )


async def validate_exploration(ctx, action):
    a = ExplorationAction.model_validate(action.model_dump())
    actor = await authorize_actor(ctx, a)
    sheet, resources = await load_actor(ctx.session, ctx.campaign_id, a.actor_id)
    if (
        a.definition.id != definition_key(a.definition)
        or a.operations != a.definition.effects
        or a.attribute != a.definition.attribute
        or a.definition.target_count != len(a.targets)
        or not _fair_cost(a, exploration_cost(a.definition, sheet.level, a.difficulty, a.resolution))
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
    if (resources.hp <= 0 or current["cannot_act"]) and not passive_wait:
        # Waiting is all a helpless hero can do, and the only way the world moves on for one; the rest is refused
        # with a line the player is shown, not a bare "invalid parameters".
        raise ActionValidationError("cannot_act")
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
            and any(getattr(target, "zone", None) == "far" for target in targets.values())  # a hero has no zone
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
    if a.resolution == "check":
        modifier = (getattr(sheet.abilities, a.attribute) - 10) // 2
        # Beyond even a lucky roll (a natural 20 and five points to spare): refused before anything is rolled or spent,
        # or a natural 20 would carry a hero across a city.
        if a.difficulty > 20 + modifier + IMPOSSIBLE_MARGIN:
            raise ActionValidationError("impossible_deed")
        # One attempt per way: this ability on this target already failed for the party, so nothing is rolled or spent.
        if a.check_target and await approach_closed(ctx.session, ctx.campaign_id, a.check_target, a.attribute):
            raise ActionValidationError("approach_closed")
    if a.definition.source == "supernatural" and a.cost < 1:
        raise ValueError("Сверхъестественное действие должно иметь положительную цену")
    if a.cost:
        have = resources.energies.get(energy_attribute(a.definition), 0)
        if have < a.cost:
            raise InsufficientEnergy(a.cost, have)
    if a.definition.source != "supernatural" and any(op.kind in MAGIC_KINDS - FREE_FOR_ORDINARY for op in a.operations):
        raise ValueError("Сверхъестественное действие не может быть бесплатным")
    if a.elapsed_game_seconds > 3600 or a.elapsed_game_seconds < 1:
        raise ValueError("Игровое действие требует положительного времени")
    refs = {f"intro:{i.ref}" for i in a.introductions}
    if len(refs) != len(a.introductions):
        raise ValueError("Повтор ссылки на предмет")
    if sum(bool(op.destination_id) for op in a.operations) > 1:
        raise ValueError("За одно действие можно перейти только в одно соседнее место")
    gifts = set()
    for index, op in enumerate(a.operations):
        if op.kind == "give":
            if not op.object_id or not op.recipient_id or op.object_id in gifts:
                raise ValueError("Нужны предмет, получатель и отдельный предмет для каждого подарка")
            gifts.add(op.object_id)
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
            obj = await ctx.session.get(Entity, ref, populate_existing=True)
            if op.kind == "give" and obj is None:
                raise ValueError("Предмет недоступен")
            if obj is not None and "loot" in obj.state:
                from app.core.universal.loot import available_loot

                taken_before = any(
                    earlier.kind == "take" and earlier.object_id == ref for earlier in a.operations[:index]
                )
                if field != "object_id" or (
                    op.kind != "take" and not (taken_before and op.kind in {"equip", "consume"})
                ):
                    raise ValueError(
                        "Предмет из сцены можно только взять; надеть или использовать его можно после take"
                    )
                if op.kind == "take":
                    available_loot(obj, actor)
                    from app.core.universal.loot import check_purchase

                    check_purchase(obj, actor)
                    difficulty = obj.state.get("take_difficulty") or 0
                    if difficulty and (a.resolution != "check" or a.difficulty < difficulty):
                        raise ValueError(
                            f"Находка редкая: взять её можно только проверкой (resolution=check) сложности "
                            f"не ниже {difficulty}"
                        )
                continue
            if obj is not None and "universal_item" in obj.state:
                from app.core.universal.inventory import _owned

                if op.kind == "give":
                    from app.core.universal.gifts import validate_gift

                    if field != "object_id":
                        raise ValueError("Подарок требует object_id")
                    await validate_gift(ctx, ref, op.recipient_id)
                    continue

                # Свое снаряжение можно использовать в действии, но нельзя превращать в сырьё.
                # Подарки NPC проверены выше отдельно от операций над обычными предметами.
                if op.kind not in {"weapon_attack", "equip", "unequip", "consume", "free_effect", "take"}:
                    raise ValueError("Снаряжение не является обычным материалом")
                _, _, item = await _owned(ctx.session, ctx.campaign_id, a.actor_id, ref)
                drawn = any(e.kind == "equip" and e.object_id == ref for e in a.operations[:index])
                if op.kind == "weapon_attack" and (
                    item.profile.kind != "weapon"
                    or not (item.equipped or drawn)
                    or item.profile.attribute != a.attribute
                ):
                    raise ValueError(
                        "Нужно надетое оружие и его характеристика: оружие не в руках достань эффектом equip "
                        "перед weapon_attack в этом же действии"
                    )
            else:
                accessible(obj, actor)
        if op.kind == "create_object":
            refs.add(f"created:{index}")
    return ValidatedExploration(actor, sheet, resources)
