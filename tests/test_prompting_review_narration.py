import asyncio
import json
from types import SimpleNamespace

from app.agents.master.exploration import obtain_exploration_action, reviewed_narration
from app.db.models import Campaign, MasterTurn
from tests.test_prompting_slicers import context
from tests.test_universal_resolution import setup


def test_review_gets_the_sliced_context(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        try:
            async with maker() as session:
                session.add(MasterTurn(id="t", campaign_id="c", status="running", trace={}))
                await session.commit()
                campaign = await session.get(Campaign, "c")
            requests = []

            async def ask(purpose, payload):
                requests.append((purpose, payload))
                return json.dumps(
                    {
                        "source": "supernatural",
                        "resolution": "automatic",
                        "effects": [{"kind": "cosmetic"}],
                    }
                    if purpose == "exploration_decide"
                    else {"verdict": "pass"}
                )

            await obtain_exploration_action(
                SimpleNamespace(maker=maker),
                campaign,
                "t",
                "m",
                {},
                context(),
                {"user_id": "u", "seat_id": "seat", "actor_id": "hero", "allowed_target_ids": frozenset({"hero"})},
                ask,
            )
            review = json.loads(
                next(payload for purpose, payload in requests if purpose == "intent_review")[-1]["content"]
            )
            assert "lore_index" in review["world_rules"]
            assert "laws" not in review["world_rules"]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_narration_context_keeps_what_the_story_needs(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        try:
            async with maker() as session:
                session.add(MasterTurn(id="t", campaign_id="c", status="running", trace={}))
                await session.commit()
            public = {
                "scene": {"location": {"id": "hall"}},
                "outcomes": {"m": {"scene_note": "Мост не создан.", "description": "Ждёт."}},
                "recent_history": [str(i) * 900 for i in range(8)],
                "knowledge": [],
            }
            requests = []

            async def ask(purpose, payload):
                requests.append(payload)
                return "Герой ждёт." if purpose == "narrate" else '{"verdict": "pass"}'

            await reviewed_narration(
                SimpleNamespace(maker=maker),
                SimpleNamespace(id="c"),
                "t",
                {},
                public["outcomes"],
                public["scene"],
                public["recent_history"],
                ask,
                context=public,
            )
            payload = json.loads(requests[0][-1]["content"])
            assert payload["scene"] == public["scene"]
            assert payload["outcomes"] == public["outcomes"]
            assert len(payload["recent_history"]) == 6
            assert all(len(line) <= 400 for line in payload["recent_history"])
            assert len(public["recent_history"]) == 8
        finally:
            await engine.dispose()

    asyncio.run(run())
