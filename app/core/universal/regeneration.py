"""Energy that comes back as game time passes, outside combat."""

from pydantic import ValidationError
from sqlalchemy import select

from app.core.campaigns import NotFound
from app.core.universal.profiles import load_actor
from app.db.models import Character, Scene
from app.rules.universal.contracts import ENERGY_KEYS
from app.rules.universal.mechanics import STEP_SECONDS, derive, energy_regen, starting_defense_bonuses


async def regenerate_energy(session, campaign_id, elapsed_seconds):
    """Give every hero's five pools back the energy of the steps that just passed, up to the pool.

    Called once per saved game step, so a replayed step restores nothing twice. Health is not an energy
    (healing and consumables own it), and nothing comes back while the scene is a combat."""
    units = -(-elapsed_seconds // STEP_SECONDS)
    scene = await session.get(Scene, campaign_id)
    if units < 1 or (scene is not None and scene.mode == "combat"):
        return
    heroes = await session.scalars(
        select(Character).where(Character.campaign_id == campaign_id, Character.status.in_(["active", "approved"]))
    )
    for hero in heroes:
        try:
            sheet, resources = await load_actor(session, campaign_id, hero.id)
        except (NotFound, ValidationError, ValueError, KeyError):
            continue  # not a universal hero
        top = derive(sheet, starting_defense_bonuses(sheet)).energy_max
        energies = {k: min(top[k], resources.energies[k] + units * energy_regen(top[k])) for k in ENERGY_KEYS}
        if energies != dict(resources.energies):
            hero.resources = {**hero.resources, "energies": {k: str(v) for k, v in energies.items()}}
