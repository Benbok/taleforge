"""Scenario inputs: persisted world facts, independent of manifest expectations."""

from sqlalchemy import select

from app.db.models import ActiveEffect, Campaign, Character, Message, NarrativeFact, Scene, Summary
from app.tools.registry import execute
from app.tools.runtime import flush_outbox, open_context
from tests.game import QueueDice, run


def setup_world(settings, cid, actors, family):
    async def prepare(s):
        campaign = await s.get(Campaign, cid)
        campaign.settings = {**campaign.settings, "summary_every": 10000}
        ctx = await open_context(s, campaign, QueueDice([]), turn_id="scenario-setup", seat_id=None)

        async def tool(name, args):
            result = await execute(ctx, name, args)
            assert result["ok"], result
            return result["result"]

        square = (await tool("create_location", {"name": "SCENARIO_SQUARE", "make_current": True}))["location_id"]
        docks = (await tool("create_location", {"name": "SCENARIO_DOCKS", "link_to": [square]}))["location_id"]
        npc = (
            await tool(
                "spawn_entity",
                {
                    "creature_template_id": "creature.commoner",
                    "name": "SCENARIO_KEEPER",
                    "location_id": square,
                    "attitude": "neutral",
                    "zone": "melee",
                },
            )
        )["spawned"][0]["id"]
        aliases = {"square": square, "docks": docks, "npc": npc}
        hero = actors["hero"]["id"]
        await tool("move", {"character_ids": list({a["id"] for a in actors.values()}), "location_id": square})
        if family == "combat_effect":
            enemy = (
                await tool(
                    "spawn_entity",
                    {
                        "creature_template_id": "creature.goblin",
                        "name": "SCENARIO_GOBLIN",
                        "location_id": square,
                        "zone": "melee" if family == "combat_effect" else "near",
                    },
                )
            )["spawned"][0]["id"]
            aliases["enemy"] = enemy
            aliases["weapon"] = next(i.id for i in ctx.world.inventory[hero] if i.item_template_id == "item.longsword")
            ctx.dice = QueueDice([20, 1])
            await tool("set_scene_mode", {"mode": "combat", "participants": [hero, enemy]})
            if family == "combat_effect":
                s.add(
                    ActiveEffect(
                        campaign_id=cid,
                        target_id=hero,
                        effect_template_id="condition.poisoned",
                        stacks=1,
                        source="scenario",
                        reason="SCENARIO_POISON",
                    )
                )
        if family == "hidden_search":
            from app.db.models import Entity

            cache = Entity(
                campaign_id=cid,
                kind="object",
                name="SCENARIO_HIDDEN_CACHE",
                description="SCENARIO_CACHE_CONTENT",
                location_id=square,
                state={"hidden": True},
            )
            s.add(cache)
            await s.flush()
            aliases["cache"] = cache.id
        if family == "multipart":
            from app.db.models import Entity

            for alias in ("first_chest", "second_chest"):
                chest = Entity(
                    campaign_id=cid, kind="object", name=f"SCENARIO_{alias.upper()}", location_id=square, state={}
                )
                s.add(chest)
                await s.flush()
                aliases[alias] = chest.id
        if family == "split_party":
            await tool("move", {"character_ids": [actors["hero_b"]["id"]], "location_id": docks})
            aliases["npc_b"] = (
                await tool(
                    "spawn_entity",
                    {
                        "creature_template_id": "creature.commoner",
                        "name": "DOCKS_ONLY_WITNESS",
                        "location_id": docks,
                        "attitude": "neutral",
                    },
                )
            )["spawned"][0]["id"]
        if family == "old_promise":
            from app.core.chat import next_seq

            for i in range(90):
                end = await next_seq(s, cid)
                s.add(Message(campaign_id=cid, seq=end, kind="narration", content=f"Дорожная запись {i}"))
                await s.flush()
            s.add(
                Summary(
                    campaign_id=cid,
                    version=1,
                    kind="rolling",
                    upto_seq=end,
                    content={"promises": ["SCENARIO_OLD_PROMISE: вернуть ключ смотрителю"]},
                )
            )
            ctx.world.entities[npc].state = {**ctx.world.entities[npc].state, "mood": "SCENARIO_FRESH_MOOD"}
        if family == "npc_motive":
            for key, value, audience in (
                ("motivation", "SCENARIO_PRIVATE_MOTIVE", ["master"]),
                ("relationship", "SCENARIO_PUBLIC_RELATION", ["master", "party"]),
            ):
                s.add(
                    NarrativeFact(
                        campaign_id=cid,
                        namespace="campaign",
                        subject_id="creature.commoner",
                        key=key,
                        kind="truth",
                        temporal_semantics="current_state",
                        freedom="committed",
                        value=value,
                        audience=audience,
                        snapshot_ref={
                            "kind": "event",
                            "source_id": "seed",
                            "version": 1,
                            "typed_address": "event:seed:1",
                        },
                    )
                )
        if family == "world_reaction":
            missing = {
                "campaign_id": cid,
                "namespace": "campaign",
                "subject_id": "missing-supply",
                "key": "situation_premise",
                "version": 1,
                "snapshot_ref": {
                    "kind": "event",
                    "source_id": "missing-event",
                    "version": 1,
                    "typed_address": "event:missing-event:1",
                },
            }
            s.add(
                NarrativeFact(
                    campaign_id=cid,
                    namespace="campaign",
                    subject_id=npc,
                    key="motivation",
                    kind="intent",
                    temporal_semantics="current_state",
                    freedom="committed",
                    value="SCENARIO_OBLIGATION_DEPENDENCY",
                    audience=["master"],
                    depends_on=[missing],
                    snapshot_ref={"kind": "event", "source_id": "seed", "version": 1, "typed_address": "event:seed:1"},
                )
            )
            scene = await s.get(Scene, cid)
            scene.state = {
                **scene.state,
                "standing": {
                    "responses": [
                        {
                            "id": "scenario-response",
                            "subject_id": npc,
                            "character_ids": [hero],
                            "status": "ready",
                            "mood": "gratitude",
                            "due_at": 0,
                            "name": "SCENARIO_KEEPER",
                            "note": "SCENARIO_READY_OBLIGATION",
                            "kind": "npc",
                            "tier": 1,
                            "target_ids": [hero],
                            "targets": ["Бран"],
                            "reason": "SCENARIO_READY_OBLIGATION",
                        }
                    ]
                },
            }
        await flush_outbox(s, ctx)
        await s.commit()
        return aliases

    return run(settings, prepare)


async def read_state(s, cid):
    """Serialize actual rows, including progress/visibility/checkpoints, for read-only oracles."""
    from app.db.models import Entity, Event, Knowledge, MasterTurn

    async def rows(model):
        return (await s.scalars(select(model).where(model.campaign_id == cid))).all()

    messages = sorted(await rows(Message), key=lambda m: m.seq)
    events = sorted(await rows(Event), key=lambda e: e.created_at)
    turns = await rows(MasterTurn)
    chars = await rows(Character)
    ids = [ch.id for ch in chars]
    knowledge = (await s.scalars(select(Knowledge).where(Knowledge.character_id.in_(ids)))).all()
    scene = await s.get(Scene, cid)
    return {
        "messages": [m.content for m in messages],
        "refs": [m.id for m in messages] + [e.id for e in events],
        "events": [
            {
                "id": e.id,
                "tool": e.tool,
                "payload": e.payload,
                "actor_id": e.actor_id,
                "target_id": e.target_id,
                "turn_id": e.turn_id,
                "dice": e.dice,
            }
            for e in events
        ],
        "turns": [t.id for t in turns if t.status == "done"],
        "world": {
            "entities": {
                e.id: {"state": e.state, "location_id": e.location_id, "zone": e.zone} for e in await rows(Entity)
            },
            "characters": {
                c.id: {"location_id": c.location_id, "resources": c.resources, "seat_id": c.seat_id} for c in chars
            },
            "knowledge": [
                {
                    "character_id": k.character_id,
                    "entity_id": k.entity_id,
                    "level": k.level,
                    "revealed": k.revealed_at is not None,
                }
                for k in knowledge
            ],
            "message_rows": [
                {
                    "id": m.id,
                    "kind": m.kind,
                    "content": m.content,
                    "seat_id": m.seat_id,
                    "turn_id": m.turn_id,
                    "visible_to": m.visible_to,
                    "data": m.data or {},
                    "intent": m.intent or {},
                }
                for m in messages
            ],
            "turn_rows": [
                {
                    "id": t.id,
                    "status": t.status,
                    "trace": t.trace,
                    "checkpoint": t.generation_checkpoint,
                    "narration_message_id": t.narration_message_id,
                }
                for t in turns
            ],
            "effects": [{"target_id": e.target_id, "template": e.effect_template_id} for e in await rows(ActiveEffect)],
            "scene": {"location_id": scene.location_id, "state": scene.state},
        },
    }
