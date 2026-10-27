"""Query-backed player projections. Reading never advances game time."""

from app.core.universal.clock import clock_view
from app.core.universal.discovery import learned_abilities
from app.core.universal.effects import active_effects, effect_label
from app.core.universal.objects import visible_objects
from app.core.universal.perception import actor_constraints
from app.core.universal.state import game_card_of


async def exploration_game_card(session, hero):
    card = game_card_of(hero, learned=await learned_abilities(session, hero.id))
    from sqlalchemy import select

    from app.core.universal.combat_actions import effective_actor
    from app.core.universal.inventory import actor_derived, item_view, owned_items, starter_views
    from app.core.universal.profiles import load_actor
    from app.core.universal.vitality import public_vitality
    from app.db.models import Entity

    card["derived"] = (await effective_actor(session, hero.campaign_id, hero.id))["derived"].model_dump(mode="json")
    inventory = [item_view(row) for row in await owned_items(session, hero.campaign_id, hero.id)]
    if (hero.resources or {}).get("inventory_initialized"):
        card["equipment"] = inventory
    else:
        inventory = starter_views(hero.campaign_id, hero.id, (await load_actor(session, hero.campaign_id, hero.id))[0])
    card["exploration"] = {
        **await clock_view(session, hero.campaign_id),
        "effects": [
            dict(
                id=e["id"],
                kind=e["kind"],
                label=effect_label(e["definition"]),
                remaining_seconds=e["remaining_seconds"],
            )
            for e in await active_effects(session, hero.campaign_id, hero.id)
        ],
        "objects": await visible_objects(session, hero.campaign_id, hero.id),
        "constraints": await actor_constraints(session, hero.campaign_id, hero.id),
    }
    enemies = []
    for enemy in await session.scalars(
        select(Entity).where(
            Entity.campaign_id == hero.campaign_id, Entity.kind == "creature", Entity.location_id == hero.location_id
        )
    ):
        from app.core.universal.visibility import visible_entity

        if not enemy.state.get("hostile") or not await visible_entity(session, hero.campaign_id, hero.id, enemy):
            continue
        if not enemy.state.get("universal_sheet"):
            enemies.append(dict(id=enemy.id, name=enemy.name, life_state="conscious", condition="В бою", hp=None))
            continue
        enemy_sheet, resources = await load_actor(session, hero.campaign_id, enemy.id)
        maximum = (await actor_derived(session, hero.campaign_id, enemy.id)).hp_max
        enemies.append(
            dict(
                id=enemy.id,
                name=enemy.name,
                life_state=public_vitality(enemy),
                condition="Ранен" if 0 < resources.hp < maximum else "Не действует" if resources.hp == 0 else "В бою",
                hp=str(resources.hp) if enemy.state.get("public_hp") else None,
            )
        )
    from app.db.models import CombatExchange, Message
    from app.rules.universal.items import GameItemAction

    pending_request = None
    for _exchange, source in await session.execute(
        select(CombatExchange, Message)
        .join(Message, Message.id == CombatExchange.source_key)
        .where(
            CombatExchange.campaign_id == hero.campaign_id,
            CombatExchange.actor_id == hero.id,
            CombatExchange.status != "rejected",
            Message.turn_id.is_(None),
        )
    ):
        binding = (source.intent or {}).get("item_control")
        if binding:
            pending_request = GameItemAction.model_validate(binding).model_dump(mode="json")
            break
    card["combat"] = dict(
        active=any(enemy["life_state"] not in {"dead", "unconscious", "stable"} for enemy in enemies),
        life_state=public_vitality(hero),
        ac=card["derived"]["ac"],
        game_seconds=card["exploration"]["game_seconds"],
        inventory=inventory,
        enemies=enemies,
        pending_request=pending_request,
        admission_pending=bool(hero.resources.get("admission_pending")),
    )
    return card
