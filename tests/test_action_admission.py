# ruff: noqa: F811 -- shared integration fixtures
"""Parser transport failures must not make visible world objects unusable."""

import asyncio
from types import SimpleNamespace

import pytest

from app.agents import intent as intents
from app.agents.llm import LLMError, LLMReply, ToolCall
from app.agents.master.parsing import ParsingMixin
from app.db.models import Entity, Event, Message
from app.gateway.ws import _quick_intent
from tests.game import party
from tests.test_intent_recovery import admin_g, dice, game_client, llm, rows  # noqa: F401
from tests.test_world_objects_transfer import ok, play
from tests.test_ws import connect, wait_message_result


@pytest.mark.parametrize("provider", ["gemini", "claude", "local"])
def test_parser_requires_structured_output_for_every_provider(provider):
    captured = {}

    async def complete(*args, **kwargs):
        captured.update(kwargs)
        return LLMReply(text="", model="test")

    service = ParsingMixin()
    service.llm = SimpleNamespace(complete=complete)
    asyncio.run(service._parse_call("test", "scene", "Осматриваюсь", {}, provider=provider))
    assert captured["tool_choice"] == {"type": "function", "function": {"name": "submit_intent"}}
    assert captured["max_tokens"] >= 1024


@pytest.mark.parametrize("failure", ["no_tool", "invalid_schema", "empty_actions", "provider_error", "timeout"])
def test_inspect_request_survives_technical_parser_failure(game_client, admin_g, llm, settings, monkeypatch, failure):
    campaign, (player,), hero = party(game_client, admin_g)
    service = game_client.app.state.master
    service.notify = lambda cid: None

    async def parse(*args, **kwargs):
        if failure == "provider_error":
            raise LLMError("provider unavailable")
        if failure == "timeout":
            raise TimeoutError("provider timeout")
        if failure == "no_tool":
            return LLMReply(text="Осмотреть пепелище", model="test")
        raw = {"actions": "invalid"} if failure == "invalid_schema" else {"kind": "action", "actions": []}
        return LLMReply(text="", model="test", tool_calls=[ToolCall("parse", "submit_intent", raw, "{}")])

    monkeypatch.setattr(service, "_parse_call", parse)
    text = "Осматриваю: Старое пепелище на предмет ценных вещей"
    with connect(game_client, player, campaign["id"]) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"text": text, "client_id": "inspect-pyre"}})
        result = wait_message_result(ws, client_id="inspect-pyre", timeout_s=5)
    assert result["type"] == "message.new", result
    (message,) = rows(settings, Message, Message.kind == "action")
    assert message.content == text
    assert message.intent["character_id"] == hero["id"]
    assert message.intent["actions"][0]["verb"] == "custom"
    assert message.intent["parser_fallback"] is True
    assert rows(settings, Event) == []  # Admission never grants a discovery or an item.


def test_parser_target_projection_matches_local_visible_objects(game_client, admin_g, settings):
    campaign, _, hero = party(game_client, admin_g)
    hid = hero["id"]

    async def scenario(ctx):
        local = (await ok(ctx, "create_location", {"name": "Пещера", "make_current": True}))["location_id"]
        remote = (await ok(ctx, "create_location", {"name": "Другой зал"}))["location_id"]
        objects = [
            Entity(campaign_id=campaign["id"], kind="object", name="Старое пепелище", location_id=local, state={}),
            Entity(campaign_id=campaign["id"], kind="object", name="Тайник", location_id=local, state={"hidden": True}),
            Entity(campaign_id=campaign["id"], kind="object", name="Чужой костёр", location_id=remote, state={}),
        ]
        ctx.session.add_all(objects)
        await ctx.session.flush()
        ctx.world.entities.update({e.id: e for e in objects})
        _, values = intents.context_for(ctx.world, ctx.world.characters[hid])
        assert objects[0].id in values["target_id"]
        assert local in values["target_id"]
        assert not {objects[1].id, objects[2].id} & set(values["target_id"])

    play(settings, campaign["id"], scenario)


@pytest.mark.parametrize("hidden", [False, True])
def test_card_inspection_uses_exact_visible_target(game_client, admin_g, llm, settings, hidden):
    campaign, _, hero = party(game_client, admin_g)
    hid = hero["id"]

    async def setup(ctx):
        place = (await ok(ctx, "create_location", {"name": "Пещера", "make_current": True}))["location_id"]
        objects = [
            Entity(
                campaign_id=campaign["id"],
                kind="object",
                name="Старое пепелище",
                location_id=place,
                state={"hidden": hidden},
            ),
            Entity(campaign_id=campaign["id"], kind="object", name="Старое пепелище", location_id=place, state={}),
        ]
        ctx.session.add_all(objects)
        await ctx.session.flush()
        return objects[0].id, ctx.world.characters[hid].seat_id

    target_id, seat_id = play(settings, campaign["id"], setup)
    parsed = game_client.portal.call(
        _quick_intent,
        game_client.app,
        campaign["id"],
        seat_id,
        {"actions": [{"verb": "inspect", "target_id": target_id}]},
    )
    if hidden:
        assert parsed.reject and "недоступен" in parsed.reject
    else:
        assert parsed.intent["actions"][0]["target_id"] == target_id
        assert parsed.intent["character_id"] == hid
    assert llm.requests == []


def test_valid_question_classification_is_preserved(game_client, admin_g, settings, monkeypatch):
    campaign, _, hero = party(game_client, admin_g)

    async def parse(*args, **kwargs):
        raw = {"kind": "question_to_master", "question": "Что я вижу?", "actions": []}
        return LLMReply(text="", model="test", tool_calls=[ToolCall("parse", "submit_intent", raw, "{}")])

    async def seat(ctx):
        return ctx.world.characters[hero["id"]].seat_id

    seat_id = play(settings, campaign["id"], seat)
    monkeypatch.setattr(game_client.app.state.master, "_parse_call", parse)
    result = game_client.portal.call(game_client.app.state.master.parse_intent, campaign["id"], seat_id, "Что я вижу?")
    assert result.intent["kind"] == "question_to_master"
