"""World Objects: read compatibility, storage invariants and SQLite/PG paths."""

import copy

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.world_objects import read_world_object
from app.db.models import (
    Campaign,
    Character,
    Entity,
    InventoryItem,
    PlotAnchorBinding,
    User,
    WorldGenerationState,
)
from tests.game import run


def test_legacy_entities_are_read_only_and_keep_visual_key():
    state = {"item": True, "qty": 2, "visual_key": "item:potion", "display_name": "Ампула"}
    entity = Entity(kind="object", name="Ампула", state=copy.deepcopy(state))
    view = read_world_object(entity)
    assert view.legacy and view.schema_version is None
    assert view.role == "item" and not view.unique
    assert view.visual_key == "item:potion" and view.metadata == {}
    assert entity.state == state
    assert "world_object" not in entity.state


def test_versioned_object_view_does_not_modify_persisted_json():
    metadata = {
        "schema_version": 1,
        "role": "container",
        "unique": True,
        "container_id": None,
        "revision": 4,
        "capabilities": ["inspect", "open"],
        "contents": {"status": "unprepared"},
    }
    entity = Entity(kind="object", name="Ларец", state={"visual_key": "item:chest", "world_object": metadata})
    view = read_world_object(entity)
    assert not view.legacy and view.schema_version == 1
    assert view.role == "container" and view.unique
    assert view.capabilities == frozenset({"inspect", "open"})
    assert view.visual_key == "item:chest" and view.revision == 4
    view.metadata["contents"]["status"] = "ready"
    assert metadata["contents"]["status"] == "unprepared"


@pytest.mark.parametrize(
    "value",
    [
        {"schema_version": 2, "role": "item"},
        {"schema_version": 1, "role": "creature"},
        {"schema_version": 1, "role": "item", "revision": -1},
        {"schema_version": 1, "role": "item", "unique": "yes"},
        {"schema_version": 1, "role": "item", "capabilities": "open"},
    ],
)
def test_versioned_object_rejects_invalid_metadata(value):
    with pytest.raises(ValueError):
        read_world_object(Entity(kind="object", name="Вещь", state={"world_object": value}))


def test_new_tables_and_legacy_inventory_are_compatible(settings):
    async def exercise(session):
        owner = User(name="world-object-test", password_hash="test")
        session.add(owner)
        await session.flush()
        campaign = Campaign(owner_id=owner.id, name="Тестовый мир", ruleset_version="1")
        session.add(campaign)
        await session.flush()

        room = Entity(campaign_id=campaign.id, kind="location", name="Комната")
        artifact = Entity(campaign_id=campaign.id, kind="object", name="Амулет", state={"item": True})
        hero = Character(campaign_id=campaign.id, name="Герой")
        session.add_all([room, artifact, hero])
        await session.flush()

        legacy = InventoryItem(character_id=hero.id, item_template_id="item.dagger")
        unique = InventoryItem(
            character_id=hero.id, item_template_id="item.amulet", world_entity_id=artifact.id
        )
        generation = WorldGenerationState(
            campaign_id=campaign.id,
            target_entity_id=room.id,
            phase="location_initial",
            status="ready",
            quality="legacy_preserved",
            source_versions=[],
            reservation={},
        )
        clue = PlotAnchorBinding(
            campaign_id=campaign.id,
            anchor_id="clue.01",
            plot_ref="plot.reveal",
            holder_entity_id=artifact.id,
            target_location_id=room.id,
            source_snapshot={"text": "Древний амулет"},
        )
        session.add_all([legacy, unique, generation, clue])
        await session.commit()
        assert legacy.world_entity_id is None
        assert unique.world_entity_id == artifact.id
        assert generation.quality == "legacy_preserved"
        assert clue.source_snapshot["text"] == "Древний амулет"

        # One physical identity must not be claimed by two inventory rows.
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(
                    InventoryItem(
                        character_id=hero.id,
                        item_template_id="item.amulet",
                        world_entity_id=artifact.id,
                    )
                )
                await session.flush()

        # Materialization and plot anchors must be unique per campaign/scope.
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(
                    WorldGenerationState(
                        campaign_id=campaign.id, target_entity_id=room.id, phase="location_initial"
                    )
                )
                await session.flush()
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(
                    PlotAnchorBinding(
                        campaign_id=campaign.id, anchor_id="clue.01", plot_ref="plot.other"
                    )
                )
                await session.flush()

    run(settings, exercise)
