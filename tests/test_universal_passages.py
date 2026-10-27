import asyncio

import pytest
from sqlalchemy import func, select

from app.core.campaigns import Viewer
from app.core.map import party_map
from app.core.universal.clock import clock_view
from app.db.models import Campaign, Character, Entity, Event, Scene, Seat, User
from tests.test_universal_resolution import setup


@pytest.mark.parametrize("variant", ["hidden_link", "hidden_door", "hidden_reverse", "locked", "closed", "open"])
def test_map_passages_use_public_states_without_disclosing_secret_connections(tmp_path, variant):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            link = {"to": "next", "label": "Туннель", "hidden": variant == "hidden_link"}
            state = {} if variant == "hidden_reverse" else {"links": [link]}
            if variant not in {"hidden_link", "hidden_reverse"}:
                state["sketch"] = {
                    "shape": "room",
                    "cols": 3,
                    "rows": 3,
                    "party": [1, 1],
                    "walls": [],
                    "features": [],
                    "exits": [
                        {
                            "name": "Дверь",
                            "to": "next",
                            "kind": "door",
                            "side": "e",
                            "at": 1,
                            "hidden": variant == "hidden_door",
                            "state": "locked" if variant == "hidden_door" else variant,
                        }
                    ],
                }
            s.add_all(
                [
                    Entity(id="here", campaign_id="c", kind="location", name="Зал", state=state),
                    Entity(
                        id="next",
                        campaign_id="c",
                        kind="location",
                        name="PRIVATE-DESTINATION",
                        state={"links": [{"to": "here", "hidden": True, "label": "SECRET"}]}
                        if variant == "hidden_reverse"
                        else {},
                    ),
                    Scene(campaign_id="c", location_id="here", state={}),
                ]
            )
            (await s.get(Character, "hero")).location_id = "here"
            await s.flush()
            viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "seat"))
            before = await clock_view(s, "c")
            view = await party_map(s, viewer)
            if variant.startswith("hidden"):
                assert view["exits"] == []
                assert "PRIVATE-DESTINATION" not in str(view)
                assert view["links"] == []
            else:
                assert view["exits"][0]["state"] == variant
                assert view["exits"][0]["kind"] == "door"
            assert await clock_view(s, "c") == before
            assert await s.scalar(select(func.count()).select_from(Event)) == 0
        await engine.dispose()

    asyncio.run(run())
