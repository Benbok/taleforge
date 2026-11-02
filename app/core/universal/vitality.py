"""Private rescue state, advanced only by saved semantic game steps."""

from sqlalchemy import select

from app.core.universal.inventory import resources_of, set_resources
from app.core.universal.profiles import actor_row, load_actor
from app.db.models import Character, Entity
from app.rules.base import DeathSaves, HitPoints
from app.rules.death import apply_death_roll
from app.rules.universal.exploration import EffectChange

SOLO_RESCUE_DC = 10  # a hero alone at the table has one throw: this much or more and they rise, otherwise they die
DOWNED = {"unconscious", "stable"}


def _seated(actor):
    return isinstance(actor, Character) and actor.seat_id is not None and actor.status in {"active", "approved"}


async def is_solo(session, campaign_id, actor):
    """A lone hero has nobody to lift them: one throw, and any blow that lands on them while they lie is death."""
    if not _seated(actor):
        return False
    seats = await session.scalars(
        select(Character.id).where(
            Character.campaign_id == campaign_id,
            Character.seat_id.is_not(None),
            Character.status.in_(["active", "approved"]),
        )
    )
    return len(list(seats)) == 1


def downed_reason(hero):
    """Why a fallen hero cannot speak or act: their player waits, and the world rolls for them."""
    if hero is not None and public_vitality(hero) in DOWNED:
        return "Герой без сознания: он не может ни говорить, ни действовать, пока его не поднимут."
    return None


def public_vitality(actor):
    stored = resources_of(actor)
    state = stored.get("vitality", {}).get("state")
    if state == "dead":
        return "dead"
    if int(stored.get("hp", "1")) > 0:
        return "conscious"
    return state if state in {"unconscious", "stable"} else "unconscious"


async def enter_zero_hp(session, campaign_id, actor_id, source_key, exchange_sequence):
    actor = await actor_row(session, campaign_id, actor_id)
    _, resources = await load_actor(session, campaign_id, actor_id)
    data = resources_of(actor)
    previous = data.get("vitality", {})
    if previous.get("state") == "dead":
        return resources
    if resources.hp > 0:
        if previous:
            set_resources(actor, {**data, "vitality": dict(state="conscious", successes="0", failures="0")})
        return resources
    if previous.get("state") in {"unconscious", "stable"}:
        return resources
    significant = (isinstance(actor, Character) and actor.seat_id is not None) or (
        isinstance(actor, Entity) and actor.state.get("significant", False)
    )
    state = dict(
        state="unconscious" if significant else "dead",
        successes="0",
        failures="0",
        eligible_sequence=str(exchange_sequence + 1),
        source_key=source_key,
    )
    set_resources(actor, {**data, "vitality": state})
    await session.flush()
    return resources


STABLE_RECOVERY_SECONDS = 3600  # an hour of saved game time brings a stable hero back to one hit point


def _recover_stable(actor, stored, state, now):
    """A stable hero used to stay at 0 HP for ever: alone at the table nobody can heal them. Time that really
    passed in the saved game (a waiting step) does."""
    since = state.get("stable_at")
    if since is None:
        set_resources(actor, {**stored, "vitality": {**state, "stable_at": str(now)}})
        return None
    if now - int(since) < STABLE_RECOVERY_SECONDS:
        return None
    state = dict(state=state_of_waking(), successes="0", failures="0")
    set_resources(actor, {**stored, "hp": "1", "vitality": state})
    return EffectChange(
        kind="vitality",
        subject_id=actor.id,
        description=f"{actor.name}: приходит в сознание.",
        data=dict(state="conscious"),
    )


def state_of_waking():
    return "conscious"


async def advance_vitality(session, campaign_id, sequence, dice, now=None):
    actors = list(await session.scalars(select(Character).where(Character.campaign_id == campaign_id)))
    actors += list(
        await session.scalars(select(Entity).where(Entity.campaign_id == campaign_id, Entity.kind == "creature"))
    )
    solo = sum(1 for actor in actors if _seated(actor)) == 1
    changes = []
    for actor in actors:
        stored = resources_of(actor)
        state = stored.get("vitality", {})
        if state.get("state") == "stable" and now is not None:
            woke = _recover_stable(actor, stored, state, now)
            if woke is not None:
                changes.append(woke)
            continue
        if state.get("state") != "unconscious" or int(state["eligible_sequence"]) > sequence:
            continue
        if int(state.get("last_sequence", "0")) >= sequence:
            continue
        if dice is None:
            raise ValueError("Для игрового спасения нужен серверный источник кубиков")
        sheet, resources = await load_actor(session, campaign_id, actor.id)
        if resources.hp > 0:
            await enter_zero_hp(session, campaign_id, actor.id, "healed", sequence)
            continue
        if solo and _seated(actor):
            changes.extend(_solo_throw(actor, stored, state, dice.d20(), sequence))
            continue
        hp = HitPoints(
            current=0,
            maximum=10 + sheet.abilities.con + 6 * (sheet.level - 1),
            death_saves=DeathSaves(int(state["successes"]), int(state["failures"])),
        )
        natural = dice.d20()
        apply_death_roll(hp, natural)
        status = (
            "dead"
            if hp.dead
            else "conscious"
            if hp.current > 0
            else "stable"
            if hp.death_saves.stable
            else "unconscious"
        )
        state = {
            **state,
            "state": status,
            "successes": str(hp.death_saves.successes),
            "failures": str(hp.death_saves.failures),
            "last_sequence": str(sequence),
        }
        if status == "stable" and now is not None:
            state["stable_at"] = str(now)
        set_resources(actor, {**stored, "hp": str(hp.current), "vitality": state})
        changes.append(
            EffectChange(
                kind="rescue_roll",
                subject_id=actor.id,
                description="Скрытая проверка состояния.",
                private=True,
                data=dict(natural=natural, successes=state["successes"], failures=state["failures"]),
            )
        )
        if status in {"dead", "stable", "conscious"}:
            description = {
                "dead": "жизнь угасла",
                "stable": "состояние стабилизировалось",
                "conscious": "приходит в сознание",
            }[status]
            changes.append(
                EffectChange(
                    kind="vitality",
                    subject_id=actor.id,
                    description=f"{actor.name}: {description}.",
                    data=dict(state=status),
                )
            )
    await session.flush()
    return changes


def _solo_throw(actor, stored, state, natural, sequence):
    """The one throw of a lone hero: success wakes them at one hit point, failure is death."""
    rose = natural >= SOLO_RESCUE_DC
    status = "conscious" if rose else "dead"
    state = {**state, "state": status, "successes": "0", "failures": "0", "last_sequence": str(sequence)}
    set_resources(actor, {**stored, "hp": "1" if rose else "0", "vitality": state})
    return [
        EffectChange(
            kind="rescue_roll",
            subject_id=actor.id,
            description="Скрытая проверка состояния.",
            private=True,
            data=dict(natural=natural, successes=state["successes"], failures=state["failures"]),
        ),
        EffectChange(
            kind="vitality",
            subject_id=actor.id,
            description=f"{actor.name}: {'приходит в сознание' if rose else 'жизнь угасла'}.",
            data=dict(state=status),
        ),
    ]


async def harm_unconscious(session, campaign_id, actor_id, source_key, sequence, *, critical=False):
    actor = await actor_row(session, campaign_id, actor_id)
    data = resources_of(actor)
    state = data.get("vitality", {})
    if state.get("state") not in {"unconscious", "stable"}:
        return
    failures = int(state.get("failures", "0")) + (2 if critical else 1)
    if await is_solo(session, campaign_id, actor):
        failures = 3  # nobody stands over a lone hero: the first blow that lands finishes them
    next_state = {**state, "state": "dead" if failures >= 3 else "unconscious", "failures": str(failures)}
    if state["state"] == "stable":
        next_state.update(successes="0", eligible_sequence=str(sequence + 1), source_key=source_key)
    set_resources(actor, {**data, "vitality": next_state})


async def progress_unconscious_party(ctx, source_key):
    """Saved world consequences follow an actual action, never a presence/disconnect timer."""
    import hashlib

    from app.core.universal.clock import complete_step
    from app.db.models import Event

    parent = await ctx.session.scalar(
        select(Event).where(Event.campaign_id == ctx.campaign_id, Event.idempotency_key == source_key)
    )
    if parent is None or parent.tool != "universal_action" or parent.actor_id != ctx.actor_id:
        raise ValueError("Событию мира нужен сохранённый источник действия")
    changes = []
    for index in range(6):
        party = list(
            await ctx.session.scalars(
                select(Character).where(
                    Character.campaign_id == ctx.campaign_id,
                    Character.seat_id.is_not(None),
                    Character.status.in_(["active", "approved"]),
                )
            )
        )
        if not party or any(public_vitality(actor) == "conscious" for actor in party):
            break
        if not any(public_vitality(actor) == "unconscious" for actor in party):
            break
        key = "world-" + hashlib.sha256(f"{source_key}:{index}".encode()).hexdigest()[:40]
        step = await complete_step(ctx.session, ctx.campaign_id, key, 6, dice=ctx.dice)
        changes.extend(EffectChange.model_validate(c) for c in step.changes)
    return changes
