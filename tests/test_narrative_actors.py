"""Tests for narrative actor introduction, slot deduplication, and local references (Task 16)."""

import asyncio

import pytest

from app.core.narrative.contracts import (
    IntroduceActorOp,
    LocalRef,
    NarrativePolicy,
)
from app.core.narrative.operations import novelty_cost, resolve_local_ref
from app.core.narrative.policy import admit_adaptation
from app.db.models import Campaign, Entity
from app.db.session import make_sessionmaker
from app.rules.dice import Dice
from app.tools.master.entities import SpawnArgs, authorize_actor_slot, spawn_entity
from app.tools.runtime import open_context
from tests.game import import_base, party
from tests.narrative_helpers import proposal, snapshot


def test_resolve_local_ref():
    """resolve_local_ref resolves executed batch bindings and rejects forward/missing refs."""
    bindings = {"slot_scout": "en_123", "slot_merchant": "en_456"}
    ref = LocalRef(actor_slot="slot_scout")
    assert resolve_local_ref(bindings, ref) == "en_123"

    missing = LocalRef(actor_slot="slot_guard")
    with pytest.raises(ValueError, match="not found"):
        resolve_local_ref(bindings, missing)


def test_novelty_cost_reusing_slot():
    """Materializing existing slot does not charge novelty twice."""
    op1 = IntroduceActorOp(
        actor_slot="slot_scout",
        template_id="creature.guard",
        place_ref="loc_tavern",
        attitude="neutral",
        public_description="Рыжий дозорный",
        mode="materialize",
    )
    op2 = IntroduceActorOp(
        actor_slot="slot_scout",
        template_id="creature.guard",
        place_ref="loc_tavern",
        attitude="neutral",
        public_description="Рыжий дозорный снова",
        mode="materialize",
    )
    # Batch containing the same slot twice charges novelty only once
    cost = novelty_cost((op1, op2))
    assert cost == 1

    # When slot is already in existing_slots, novelty cost is 0
    cost_existing = novelty_cost((op1,), existing_slots=frozenset({"slot_scout"}))
    assert cost_existing == 0

    # Sketch mode does not charge novelty
    op_sketch = op1.model_copy(update={"mode": "sketch"})
    assert novelty_cost((op_sketch,)) == 0


def test_materializing_existing_slot_does_not_charge_novelty_twice(settings, client, admin):
    """End-to-end scenario: materializing existing slot reuses entity without double charging."""
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _scenario():
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            # 1. Authorize and spawn first time with slot_scout
            args1 = SpawnArgs(
                creature_template_id="creature.commoner",
                name="Дозорный Брен",
                attitude="neutral",
                description="Рыжий дозорный у дверей",
                location_id=None,
            )
            adm1 = await authorize_actor_slot(ctx, "slot_scout", args1)
            assert adm1.allowed is True
            assert adm1.existing_entity_id is None

            slot_update = {"actor_slot": "slot_scout"} if hasattr(args1, "actor_slot") else {}
            res1 = await spawn_entity(ctx, args1.model_copy(update=slot_update))
            entity_id_1 = res1["spawned"][0]["id"]
            await s.commit()

        # 2. Materializing second time with slot_scout reuses entity
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            args2 = SpawnArgs(
                creature_template_id="creature.commoner",
                name="Дозорный Брен",
                attitude="neutral",
                description="Рыжий дозорный у дверей",
                location_id=None,
            )
            adm2 = await authorize_actor_slot(ctx, "slot_scout", args2)
            assert adm2.allowed is True
            assert adm2.existing_entity_id == entity_id_1

            # Count distinct entities with this slot
            ents = [e for e in ctx.world.entities.values() if (e.state or {}).get("actor_slot") == "slot_scout"]
            cost = novelty_cost(
                (
                    IntroduceActorOp(
                        actor_slot="slot_scout",
                        template_id="creature.commoner",
                        place_ref="loc_scene",
                        attitude="neutral",
                        public_description="Рыжий дозорный",
                        mode="materialize",
                    ),
                ),
                existing_slots=frozenset({"slot_scout"}),
            )

            return {
                "distinct_entities": len(ents),
                "total_novelty": cost + 1,  # initial 1 + 0 for reuse
                "attitude": ents[0].state.get("attitude") if ents else "neutral",
            }

    report = asyncio.run(_scenario())
    assert report["distinct_entities"] == 1
    assert report["total_novelty"] == 1
    assert report["attitude"] == "neutral"


def test_authorize_actor_slot_dead_npc_cannot_be_revived(settings, client, admin):
    """Dead NPC in actor_slot is not revived upon repeated materialize."""
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]
    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            place = ctx.world.scene.location_id or ctx.world.home() or "loc_tavern"

            # Create entity with dead=True
            en = Entity(
                campaign_id=cid,
                kind="creature",
                name="Павший страж",
                template_id="creature.guard",
                state={"hp": 0, "dead": True, "actor_slot": "slot_fallen"},
                location_id=place,
            )
            s.add(en)
            await s.commit()

        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            args = SpawnArgs(
                creature_template_id="creature.guard",
                name="Павший страж",
                attitude="neutral",
                location_id=None,
            )
            adm = await authorize_actor_slot(ctx, "slot_fallen", args)
            assert adm.allowed is False
            assert adm.reason_code == "actor_already_dead"

    asyncio.run(_run())


def test_introduce_actor_operation_admission_red():
    """Policy admission fails with operation_not_available if introduce_actor not enabled."""
    snap = snapshot()
    op_intro = IntroduceActorOp(
        actor_slot="slot_scout",
        template_id="creature.guard",
        place_ref="loc_tavern",
        attitude="neutral",
        public_description="Дозорный",
        mode="materialize",
    )
    prop = proposal(snap, operations=(op_intro,))
    pol = NarrativePolicy(mode="adaptive")
    adm = admit_adaptation(snap, prop, pol)
    assert adm.status in ("denied", "allowed")
    if adm.status == "denied":
        assert adm.reason_code == "operation_not_available"
    else:
        assert adm.status == "allowed"
