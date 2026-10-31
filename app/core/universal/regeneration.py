"""Energy that comes back as game time passes, outside combat."""

from pydantic import ValidationError
from sqlalchemy import select

from app.core.campaigns import NotFound
from app.core.universal.profiles import load_actor
from app.db.models import Character
from app.rules.universal.contracts import ENERGY_KEYS
from app.rules.universal.mechanics import STEP_SECONDS, derive, energy_regen, starting_defense_bonuses

HEALTH_REGEN_SECONDS = 600


async def regenerate_health(session, campaign_id, elapsed_seconds: int) -> None:
    """Медленно восстановить здоровье, сохранив остаток времени между шагами."""
    from app.core.universal.encounters import in_combat

    if elapsed_seconds <= 0:
        return
    for hero in await session.scalars(
        select(Character).where(Character.campaign_id == campaign_id, Character.status.in_(["active", "approved"]))
    ):
        if await in_combat(session, campaign_id, hero.location_id):
            continue
        try:
            sheet, resources = await load_actor(session, campaign_id, hero.id)
        except (NotFound, ValidationError, ValueError, KeyError):
            continue
        top = derive(sheet, starting_defense_bonuses(sheet)).hp_max
        if resources.hp <= 0 or resources.hp >= top:
            continue
        seconds = int(hero.resources.get("hp_regen_carry", "0")) + elapsed_seconds
        gain, carry = divmod(seconds, HEALTH_REGEN_SECONDS)
        hp = min(top, resources.hp + gain)
        hero.resources = {**hero.resources, "hp": str(hp), "hp_regen_carry": str(carry if hp < top else 0)}


async def regenerate_energy(session, campaign_id, elapsed_seconds):
    """Give every hero's five pools back the energy of the steps that just passed, up to the pool.

    Called once per saved game step, so a replayed step restores nothing twice. Health is not an energy
    (healing and consumables own it), and nothing comes back while the scene is a combat."""
    units = -(-elapsed_seconds // STEP_SECONDS)
    if units < 1:
        return
    heroes = await session.scalars(
        select(Character).where(Character.campaign_id == campaign_id, Character.status.in_(["active", "approved"]))
    )
    from app.core.universal.encounters import in_combat

    for hero in heroes:
        if await in_combat(session, campaign_id, hero.location_id):
            continue
        try:
            sheet, resources = await load_actor(session, campaign_id, hero.id)
        except (NotFound, ValidationError, ValueError, KeyError):
            continue  # not a universal hero
        top = derive(sheet, starting_defense_bonuses(sheet)).energy_max
        energies = {k: min(top[k], resources.energies[k] + units * energy_regen(top[k])) for k in ENERGY_KEYS}
        if energies != dict(resources.energies):
            hero.resources = {**hero.resources, "energies": {k: str(v) for k, v in energies.items()}}
