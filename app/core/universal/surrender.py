"""A beaten foe may give up: when little health is left it begs, bargains or talks instead of striking, as its temper
allows. A fanatic never yields; the others yield by the roll of a die, so the table can see it was luck and not a
whim of the writer. A foe that yielded does not attack again unless the hero strikes it afterwards."""

from app.core.universal.profiles import load_actor
from app.db.models import Entity
from app.rules.universal.exploration import EffectChange

# Yields when a d20 shows at most this much, at the moment it would have struck back.
TEMPER_CHANCE = {"fanatic": 0, "brave": 3, "wary": 8, "cowardly": 16}
LOW_SHARE = 4  # a quarter of its health...
LOW_CAP = 5  # ...and never more than this much, so a large beast is not spared at a third of its strength
TEMPER_RU = {
    "fanatic": "фанатик",
    "brave": "храбрый",
    "wary": "расчётливый",
    "cowardly": "трусливый",
}


def is_low(hp: int, hp_max: int) -> bool:
    return 0 < hp <= min(LOW_CAP, max(1, hp_max // LOW_SHARE))


async def take_pleas(ctx, choices):
    """Foes among the would-be repliers that yield now: they are marked, and what they do is returned as changes
    for the writer. The rest may still reply."""
    from app.core.universal.inventory import actor_derived

    s = ctx.session
    pleas, remaining = [], []
    for choice in choices:
        foe = await s.get(Entity, choice["actor_id"], populate_existing=True)
        temper = foe.state.get("temper", "brave")
        chance = TEMPER_CHANCE.get(temper, TEMPER_CHANCE["brave"])
        _, resources = await load_actor(s, ctx.campaign_id, foe.id)
        derived = await actor_derived(s, ctx.campaign_id, foe.id)
        if chance and ctx.dice is not None and is_low(resources.hp, derived.hp_max) and ctx.dice.d20() <= chance:
            foe.state = {**foe.state, "yielded": True}
            pleas.append(
                EffectChange(
                    kind="plea",
                    subject_id=foe.id,
                    description=(
                        f"{foe.name} изранен и больше не нападает: просит пощады или пытается заговорить "
                        f"(нрав: {TEMPER_RU.get(temper, temper)})."
                    ),
                    data={"temper": temper},
                )
            )
        else:
            remaining.append(choice)
    return pleas, remaining
