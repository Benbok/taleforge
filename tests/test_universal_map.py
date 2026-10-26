import asyncio
import json

import pytest
from sqlalchemy import func, select

from app.core.campaigns import Viewer
from app.core.map import party_map
from app.core.universal.clock import clock_view
from app.db.models import Campaign, Character, Entity, Event, Scene, Seat, User
from tests.test_universal_resolution import setup


def test_universal_map_is_read_only_and_hides_private_inventory(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.location_id = "entry"
            s.add(Scene(campaign_id="c", location_id="entry"))
            s.add_all(
                [
                    Entity(
                        id="entry",
                        campaign_id="c",
                        kind="location",
                        name="Entry",
                        description="Known clearing",
                        state={
                            "sketch": {
                                "shape": "room",
                                "cols": 2,
                                "rows": 2,
                                "party": [0, 0],
                                "walls": [],
                                "exits": [],
                                "features": [
                                    {
                                        "name": "PRIVATE FEATURE",
                                        "kind": "object",
                                        "entity_id": "private",
                                        "cells": [[0, 0, 0, 0]],
                                    }
                                ],
                            }
                        },
                    ),
                    Entity(id="visible", campaign_id="c", kind="object", name="Visible stone", location_id="entry"),
                    Entity(
                        id="private",
                        campaign_id="c",
                        kind="creature",
                        name="PRIVATE NPC",
                        location_id="entry",
                        state={"visibility": "private"},
                    ),
                    Entity(
                        id="secret",
                        campaign_id="c",
                        kind="object",
                        name="SECRET CHEST",
                        location_id="entry",
                        state={"secret": True},
                    ),
                ]
            )
            await s.flush()
            from app.core.universal.inventory import create_item
            from app.rules.universal.items import ItemProfile

            item = await create_item(s, "c", "hero", ItemProfile(name="OWNED INVENTORY", kind="weapon"), "map-item")
            item.location_id = "entry"
            await s.commit()
            viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "seat"))
            before = await clock_view(s, "c")
            view = await party_map(s, viewer)
            text = json.dumps(view)
            assert "Visible stone" in text
            assert "PRIVATE NPC" not in text and "SECRET CHEST" not in text and "OWNED INVENTORY" not in text
            assert "PRIVATE FEATURE" not in text
            assert await clock_view(s, "c") == before
            assert await s.scalar(select(func.count()).select_from(Event)) == 0
            assert hero.location_id == "entry"
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("handler_name", ["_step", "_traverse", "_route"])
def test_universal_tactical_socket_requests_are_rejected_before_any_world_context(tmp_path, monkeypatch, handler_name):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.core.layout import transit
    from app.gateway import ws
    from app.tools import runtime

    async def run():
        engine, maker = await setup(tmp_path)
        forbidden = AsyncMock(side_effect=AssertionError("Tactical mutation was opened"))
        monkeypatch.setattr(runtime, "open_context", forbidden)
        monkeypatch.setattr(transit, "traverse", forbidden)
        messages = []

        async def send(value):
            messages.append(value)

        conn = SimpleNamespace(campaign_id="c", send=send)
        app = SimpleNamespace(
            state=SimpleNamespace(sessionmaker=maker, dice_factory=lambda: None, master=SimpleNamespace(preparer=None))
        )
        async with maker() as s:
            user = await s.get(User, "u")
        await getattr(ws, handler_name)(
            app, user, conn, dict(request_id="old-client", cell=[0, 0], passage_ref="passage", route_ref="route")
        )
        assert messages[-1]["payload"]["reason"] == "orientation_only"
        assert not forbidden.called
        async with maker() as s:
            assert (await clock_view(s, "c"))["step_index"] == "0"
            assert await s.scalar(select(func.count()).select_from(Event)) == 0
        await engine.dispose()

    asyncio.run(run())


def test_chat_move_uses_known_destination_without_cell_or_map_command(tmp_path):
    from app.core.universal.combat import run_exchange
    from app.core.universal.interpretation import compile_exploration
    from app.core.universal.resolution import ResolutionContext
    from app.db.models import Message
    from app.rules.dice import FixedDice
    from app.rules.universal.exploration import EffectIntentV2, IntentReview, IntentV2

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Scene(campaign_id="c", location_id="entry"))
            s.add_all(
                [
                    Entity(
                        id="entry",
                        campaign_id="c",
                        kind="location",
                        name="Entry",
                        state={"links": [{"to": "next", "label": "Trail"}]},
                    ),
                    Entity(id="next", campaign_id="c", kind="location", name="Grove"),
                ]
            )
            hero = await s.get(Character, "hero")
            hero.location_id = "entry"
            s.add(
                Message(
                    id="move",
                    campaign_id="c",
                    seq=1,
                    seat_id="seat",
                    author_user_id="u",
                    kind="action",
                    content="Иду в рощу",
                )
            )
            await s.flush()
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            intent = IntentV2(
                source="mundane", resolution="automatic", effects=[EffectIntentV2(kind="move", destination_id="next")]
            )
            action = await compile_exploration(
                ctx,
                intent,
                IntentReview(verdict="pass"),
                dict(source_message_id="move", source_text="Иду в рощу", evidence=""),
            )
            outcome = await run_exchange(ctx, action, request_key="move")
            assert outcome[0].success and hero.location_id == "next"
            assert (await clock_view(s, "c"))["step_index"] == "1"
            await run_exchange(ctx, action, request_key="move")
            assert (await clock_view(s, "c"))["step_index"] == "1"
        await engine.dispose()

    asyncio.run(run())


def test_map_read_does_not_create_scene_for_an_unstarted_campaign(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "seat"))
            assert await s.get(Scene, "c") is None
            await party_map(s, viewer)
            assert await s.get(Scene, "c") is None
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("variant", ["missing", "foreign", "private", "unlinked", "locked"])
def test_chat_travel_rejects_unreachable_destination_before_dice(tmp_path, variant):
    from app.core.universal.interpretation import compile_exploration
    from app.core.universal.resolution import ResolutionContext
    from app.db.models import Message
    from app.rules.dice import FixedDice
    from app.rules.universal.exploration import EffectIntentV2, IntentReview, IntentV2

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Scene(campaign_id="c", location_id="entry"))
            state = {"links": [{"to": "next"}]} if variant != "unlinked" else {}
            if variant == "locked":
                state["sketch"] = {
                    "shape": "room",
                    "cols": 2,
                    "rows": 2,
                    "party": [0, 0],
                    "walls": [],
                    "features": [],
                    "exits": [
                        {"name": "Locked door", "side": "e", "at": 0, "kind": "door", "state": "locked", "to": "next"}
                    ],
                }
            s.add(Entity(id="entry", campaign_id="c", kind="location", name="Entry", state=state))
            (await s.get(Character, "hero")).location_id = "entry"
            if variant == "foreign":
                s.add(
                    Campaign(
                        id="other", owner_id="u", name="Other", ruleset_id="universal", ruleset_version="universal.v1"
                    )
                )
                await s.flush()
            if variant != "missing":
                s.add(
                    Entity(
                        id="next",
                        campaign_id="other" if variant == "foreign" else "c",
                        kind="location",
                        name="Next",
                        state={"visibility": "private"} if variant == "private" else {},
                    )
                )
            s.add(
                Message(
                    id="move",
                    campaign_id="c",
                    seq=1,
                    seat_id="seat",
                    author_user_id="u",
                    kind="action",
                    content="Иду дальше",
                )
            )
            await s.flush()
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            intent = IntentV2(
                source="mundane", resolution="automatic", effects=[EffectIntentV2(kind="move", destination_id="next")]
            )
            with pytest.raises(ValueError):
                await compile_exploration(
                    ctx,
                    intent,
                    IntentReview(verdict="pass"),
                    dict(source_message_id="move", source_text="Иду дальше", evidence=""),
                )
            assert (await clock_view(s, "c"))["step_index"] == "0"
        await engine.dispose()

    asyncio.run(run())
