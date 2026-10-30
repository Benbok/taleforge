"""The same audience-safe decision context for live turns and evaluation snapshots."""

from sqlalchemy import select

from app.agents.master.universal_narration import recent_history
from app.core.campaigns import Viewer
from app.core.universal.profiles import load_actor
from app.db.models import CampaignSecret, HeroAbility, User


async def build_decide_context(session, campaign, hero, seat, msg_text, *, upto_seq=2**63 - 1, audience=None):
    from app.agents.master.universal import world_rules
    from app.core.universal.world_generation import enabled as world_enabled

    s, c, cid = session, campaign, campaign.id
    sh, resources = await load_actor(s, cid, hero.id)
    secret = await s.get(CampaignSecret, cid)
    from app.core.universal.inventory import ensure_inventory, item_view, owned_items
    from app.core.universal.scene import universal_scene

    await ensure_inventory(s, cid, hero.id)
    inventory = [item_view(row) for row in await owned_items(s, cid, hero.id)]
    await s.commit()
    user = await s.get(User, seat.user_id)
    public_scene = await universal_scene(s, c, Viewer(user, c, seat))
    from app.core.map import party_map

    known_exits = (await party_map(s, Viewer(user, c, seat)))["exits"]
    known = list(await s.scalars(select(HeroAbility).where(HeroAbility.character_id == hero.id)))
    history = await recent_history(s, c, upto_seq, audience, public_scene)
    from app.core.universal.objects import visible_objects
    from app.core.universal.perception import actor_constraints, established_evidence

    evidence = await established_evidence(s, cid, hero.id)
    objects = await visible_objects(s, cid, hero.id)
    constraints = await actor_constraints(s, cid, hero.id)
    from app.core.universal.effects import active_effects

    running = [
        dict(
            id=e["id"],
            kind=e["kind"],
            label=e["definition"].get("label") or e["kind"],
            description=e["definition"].get("appearance") or "",
            remaining_seconds=e["remaining_seconds"],
        )
        for e in await active_effects(s, cid, hero.id)
    ]
    return dict(
        world_development=bool(world_enabled(c)),
        world=(secret.setting or {}).get("studio", {}) if secret else {},
        # The text of the world decides what is allowed; the private notes stay with the master.
        world_rules=world_rules(secret),
        hero=sh.model_dump(mode="json"),
        resources=resources.model_dump(mode="json"),
        scene=public_scene,
        history=history,
        source=msg_text,
        established_evidence=evidence,
        objects=objects,
        inventory=inventory,
        known_exits=known_exits,
        constraints=constraints,
        active_effects=running,
        known_abilities=[
            dict(name=a.name, profile_id=a.profile_ref, revision=a.profile_revision, profile=a.definition)
            for a in known
        ],
    )
