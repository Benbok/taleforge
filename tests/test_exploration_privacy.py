import asyncio

import pytest

from app.core.campaigns import Viewer
from app.core.inspect import InspectError, entity_card
from app.core.universal.objects import apply_object_operation
from app.core.universal.perception import established_evidence
from app.core.universal.resolution import ResolutionContext
from app.db.models import Campaign, Character, Entity, Event, Message, User
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2
from tests.test_universal_resolution import setup


def test_private_narration_is_not_material_evidence_and_foreign_cup_cannot_be_inspected(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Entity(id="place", campaign_id="c", kind="location", name="Руины", description="Пустой зал."))
            (await s.get(Character, "hero")).location_id = "place"
            for seq, audience, data in [
                (1, ["seat"], {"scope": "private"}),
                (2, ["seat"], {"whisper_reply": "m"}),
                (3, ["other"], {"scope": "party"}),
            ]:
                s.add(
                    Message(
                        campaign_id="c",
                        seq=seq,
                        kind="narration",
                        content="PRIVATE-MATERIAL",
                        visible_to=audience,
                        data={**data, "location_id": "place"},
                    )
                )
            event = Event(id="event", campaign_id="c", actor_id="target", tool="universal_action", payload={})
            s.add(event)
            await s.flush()
            assert "PRIVATE-MATERIAL" not in await established_evidence(s, "c", "hero")
            ctx = ResolutionContext(s, "c", "u", "seat", "target", FixedDice([]))
            change = await apply_object_operation(ctx, EffectIntentV2(kind="create_object"), event)
            campaign = await s.get(Campaign, "c")
            viewer = Viewer(await s.get(User, "u"), campaign, next(x for x in campaign.seats if x.id == "seat"))
            with pytest.raises(InspectError):
                await entity_card(s, viewer, change.subject_id)
        await engine.dispose()

    asyncio.run(run())
