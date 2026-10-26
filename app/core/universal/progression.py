"""Campaign-serialized progression with durable receipts and trusted resource resizing."""

import hashlib

from sqlalchemy import select

from app.core.campaigns import AccessDenied, Conflict
from app.core.universal.clock import lock_campaign
from app.core.universal.profiles import ActorResources, load_actor, save_actor
from app.core.universal.vitality import enter_zero_hp
from app.db.models import Character, Event
from app.rules.universal.mechanics import derive
from app.rules.universal.progression import grant_xp, natural


def receipt_key(kind, source):
    if not isinstance(source, str) or not source or len(source) > 256:
        raise ValueError("Нужен ключ события")
    return kind + "-" + hashlib.sha256(source.encode()).hexdigest()[:40]


def resize_resources(resources, before, after, *, dead=False):
    old, new = derive(before, []), derive(after, [])
    return ActorResources(
        hp=0 if dead else min(new.hp_max, resources.hp + max(0, new.hp_max - old.hp_max)),
        energies={
            k: min(new.energy_max[k], value + max(0, new.energy_max[k] - old.energy_max[k]))
            for k, value in resources.energies.items()
        },
        effects=resources.effects,
    )


async def persist_growth(session, actor, before, after):
    _, resources = await load_actor(session, actor.campaign_id, actor.id)
    dead = actor.resources.get("vitality", {}).get("state") == "dead"
    resized = resize_resources(resources, before, after, dead=dead)
    await save_actor(session, actor.campaign_id, actor.id, after, resized)
    actor.resources = {
        **actor.resources,
        "progression_revision": int(actor.resources.get("progression_revision", 1)) + 1,
    }
    if not dead:
        await enter_zero_hp(session, actor.campaign_id, actor.id, "growth", 0)
    await session.flush()


async def award_xp(session, campaign_id, source_key, actor_ids, amount, *, reason="Достижение"):
    natural(amount, 1)
    if not actor_ids or len(actor_ids) != len(set(actor_ids)):
        raise ValueError("Нужны разные участники")
    binding = dict(actor_ids=sorted(actor_ids), amount=str(amount), reason=reason)
    key = receipt_key("xp", source_key)
    async with session.begin_nested():
        await lock_campaign(session, campaign_id)
        previous = await session.scalar(
            select(Event).where(Event.campaign_id == campaign_id, Event.idempotency_key == key)
        )
        if previous:
            if previous.tool != "universal_xp" or previous.payload["binding"] != binding:
                raise Conflict("Награда события уже сохранена")
            return binding["actor_ids"]
        heroes = []
        for aid in binding["actor_ids"]:
            hero = await session.get(Character, aid, populate_existing=True)
            if hero is None or hero.campaign_id != campaign_id or hero.status not in {"active", "approved"}:
                raise AccessDenied("Получатель не является действующим героем кампании")
            before, _ = await load_actor(session, campaign_id, aid)
            heroes.append((hero, before, grant_xp(before, amount)))
        for hero, before, after in heroes:
            await persist_growth(session, hero, before, after)
        session.add(
            Event(
                campaign_id=campaign_id,
                tool="universal_xp",
                idempotency_key=key,
                payload=dict(binding=binding, source=source_key),
            )
        )
        await session.flush()
    return binding["actor_ids"]
