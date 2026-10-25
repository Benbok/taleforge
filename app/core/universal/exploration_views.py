"""Query-backed player projections. Reading never advances game time."""

from app.core.universal.clock import clock_view
from app.core.universal.discovery import learned_abilities
from app.core.universal.effects import active_effects
from app.core.universal.objects import visible_objects
from app.core.universal.perception import actor_constraints
from app.core.universal.state import game_card_of


async def exploration_game_card(session, hero):
    card = game_card_of(hero, learned=await learned_abilities(session, hero.id))
    labels = {
        "change_form": "Форма куста",
        "camouflage": "Маскировка",
        "illumination": "Освещение",
        "hold_breath": "Задержка дыхания",
    }
    card["exploration"] = {
        **await clock_view(session, hero.campaign_id),
        "effects": [
            dict(
                id=e["id"],
                kind=e["kind"],
                label=e["definition"].get("label") or labels.get(e["kind"], "Эффект"),
                remaining_seconds=e["remaining_seconds"],
            )
            for e in await active_effects(session, hero.campaign_id, hero.id)
        ],
        "objects": await visible_objects(session, hero.campaign_id, hero.id),
        "constraints": await actor_constraints(session, hero.campaign_id, hero.id),
    }
    return card
