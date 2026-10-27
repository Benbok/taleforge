# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Парсер намерений: отказы, уточнения, лимит действий в бою, пропавший предмет, маршрутизатор атаки."""

from sqlalchemy import select

from app.agents import intent as intents
from app.db.models import Campaign, InventoryItem
from app.tools.action_plan import approach_attack
from app.tools.runtime import open_context
from tests.game import QueueDice, run
from tests.test_combat import _fight, scene  # noqa: F401
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_ws import connect


def intent(*actions, confidence=0.95, problem="none", question=None):
    return {
        "tool_calls": [
            (
                "submit_intent",
                {
                    "kind": "action",
                    "actions": list(actions),
                    "confidence": confidence,
                    "problem": problem,
                    "question": question,
                },
            )
        ]
    }


def send(client, head, cid, text):
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": text}})
        e = ws.receive_json()
        while e["type"] not in ("message.rejected", "message.new"):
            e = ws.receive_json()
        return e


def goblin_in_melee(settings, cid, hero, *, fight=False):
    async def go(s):
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice([]), turn_id=None, seat_id=None)
        if fight:
            gob = await _fight(ctx, hero, "creature.goblin", zone="melee", first="hero")
            from app.core import combat

            combat._begin_hero_turn(ctx, ctx.world.characters[hero])
        else:
            from app.tools.registry import execute

            r = await execute(
                ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин", "zone": "melee"}
            )
            gob = r["result"]["spawned"][0]["id"]
        sword = (
            await s.scalars(
                select(InventoryItem).where(
                    InventoryItem.character_id == hero, InventoryItem.item_template_id == "item.longsword"
                )
            )
        ).first()
        await s.commit()
        return gob, sword.id

    return run(settings, go)


def send_auto(client, head, cid, text, **extra):
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"text": text, **extra}})
        e = ws.receive_json()
        while e["type"] not in ("message.rejected", "message.new"):
            e = ws.receive_json()
        return e


def test_describe_and_route_helpers():
    from app.agents.llm import parser_model_for
    from app.config import settings as app_settings

    # пара моделей задаётся в .env: техническая модель провайдера, явная модель только получает префикс
    assert parser_model_for("gemini") == "gemini/" + app_settings.gemini_technical_model
    assert parser_model_for("claude") == app_settings.claude_technical_model
    assert parser_model_for("gemini", "gemini-2.5-flash") == "gemini/gemini-2.5-flash"

    it = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "attack", "target_id": "en1", "instrument_id": "inv1", "manner": ""}],
    }
    assert intents.routable_attack(it) == {"attacker_id": "ch1", "target_id": "en1", "attack": "inv1"}
    assert intents.routable_attack({**it, "confidence": 0.6}) is None
    assert "attack target_id=en1" in intents.describe(it)
    spec = intents.tool_spec({"target_id": ["en1"], "instrument_id": []})
    act_props = spec["function"]["parameters"]["properties"]["actions"]["items"]["properties"]
    assert act_props["target_id"]["anyOf"][0]["enum"] == ["en1"] and "$ref" not in str(spec)

    # routable_tool_call: use_item
    item_it = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "use_item", "instrument_id": "pot1", "manner": ""}],
    }
    assert intents.routable_tool_call(item_it) == ("use_item", {"character_id": "ch1", "inventory_id": "pot1"})

    # routable_tool_call: rest
    rest_short = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "rest", "manner": "короткий отдых"}],
    }
    assert intents.routable_tool_call(rest_short) == ("rest", {"character_ids": ["ch1"], "kind": "short"})
    rest_long = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "rest", "manner": "длинный отдых на ночь"}],
    }
    assert intents.routable_tool_call(rest_long) == ("rest", {"character_ids": ["ch1"], "kind": "long"})

    # routable_tool_call: skill checks
    hide_it = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "hide", "manner": "в тени"}],
    }
    assert intents.routable_tool_call(hide_it) == (
        "roll_check",
        {"character_id": "ch1", "stat": "stealth", "kind": "check", "difficulty": "dc.medium", "reason": "в тени"},
    )
    search_it = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "search", "skill": "investigation", "manner": "ищу тайник"}],
    }
    assert intents.routable_tool_call(search_it) == (
        "roll_check",
        {
            "character_id": "ch1",
            "stat": "investigation",
            "kind": "check",
            "difficulty": "dc.medium",
            "reason": "ищу тайник",
        },
    )


def test_litellm_prompt_caching_injection(monkeypatch):
    import litellm

    from app.agents.llm import LiteLLMClient

    captured_kwargs = {}

    async def mock_acompletion(**kwargs):
        captured_kwargs.update(kwargs)
        from unittest.mock import MagicMock

        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message = MagicMock(content="ok", tool_calls=[])
        resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        return resp

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    client = LiteLLMClient()
    import asyncio

    # Gemini uses implicit caching: character count cannot prove its token minimum.
    long_sys = "Правила мира. " * 100
    msgs = [{"role": "system", "content": long_sys}, {"role": "user", "content": "Привет"}]
    asyncio.run(client.complete(msgs, model="gemini/gemini-2.5-flash"))
    assert captured_kwargs["messages"][0]["content"] == long_sys

    # Anthropic retains explicit ephemeral caching.
    asyncio.run(client.complete(msgs, model="anthropic/claude-sonnet-4-5"))
    sys_content = captured_kwargs["messages"][0]["content"]
    assert isinstance(sys_content, list)
    assert sys_content[0]["cache_control"] == {"type": "ephemeral"}

    # Для локальной модели — не трогаем (остаётся строкой)
    asyncio.run(client.complete(msgs, model="lm_studio/qwen2.5"))
    assert captured_kwargs["messages"][0]["content"] == long_sys


def test_approach_attack_plan_preserves_order_and_confidence():
    plan = {
        "character_id": "ch_hero",
        "confidence": 0.95,
        "actions": [
            {"verb": "move", "target_id": "en_goblin", "zone": "melee"},
            {"verb": "attack", "target_id": "en_goblin", "instrument_id": "inv_sword"},
        ],
    }
    assert approach_attack(plan) == {"attacker_id": "ch_hero", "target_id": "en_goblin", "attack": "inv_sword"}
    assert approach_attack({**plan, "actions": list(reversed(plan["actions"]))}) is None
    assert approach_attack({**plan, "confidence": 0.5}) is None
    assert approach_attack({**plan, "actions": [{**plan["actions"][0], "zone": "far"}, plan["actions"][1]]}) is None
    missing = [plan["actions"][0], {**plan["actions"][1], "missing_item": True}]
    assert approach_attack({**plan, "actions": missing}) is None


def test_class_features_are_routed_only_when_explicitly_declared():
    base = {
        "character_id": "ch1",
        "confidence": 0.95,
        "actions": [{"verb": "attack", "target_id": "en1", "instrument_id": "inv1"}],
    }
    ordinary = {"attacker_id": "ch1", "target_id": "en1", "attack": "inv1"}
    assert intents.routable_attack(base) == ordinary
    enhanced = {
        **base,
        "actions": [{**base["actions"][0], "reckless": True, "stunning_strike": True}],
    }
    assert intents.routable_attack(enhanced) == {**ordinary, "reckless": True, "stunning_strike": True}
    # Vivid prose without the explicit feature flags cannot grant advantage.
    flavor = {**base, "actions": [{**base["actions"][0], "manner": "яростно, прыгая на врага"}]}
    assert intents.routable_attack(flavor) == ordinary


def test_shove_routes_to_contested_tool_not_fixed_dc_check():
    base = {"character_id": "ch1", "confidence": 0.95}
    prone = {"verb": "shove", "target_id": "en1", "maneuver": "prone"}
    push = {**prone, "maneuver": "push"}
    assert intents.routable_tool_call({**base, "actions": [prone]}) == (
        "resolve_shove",
        {"attacker_id": "ch1", "target_id": "en1", "technique": "prone"},
    )
    assert intents.routable_tool_call({**base, "actions": [push]}) == (
        "resolve_shove",
        {"attacker_id": "ch1", "target_id": "en1", "technique": "push"},
    )
    assert intents.routable_tool_call({**base, "actions": [{**prone, "maneuver": None}]}) is None
    assert intents.routable_tool_call({**base, "actions": [{**prone, "target_id": None}]}) is None
    assert intents.routable_tool_call({**base, "actions": [{"verb": "grapple", "target_id": "en1"}]}) == (
        "resolve_grapple",
        {"attacker_id": "ch1", "target_id": "en1"},
    )


def test_grapple_and_escape_are_routed_to_real_tools():
    base = {"character_id": "ch_hero", "confidence": 0.9}
    assert intents.routable_tool_call({**base, "actions": [{"verb": "grapple", "target_id": "en1"}]}) == (
        "resolve_grapple",
        {"attacker_id": "ch_hero", "target_id": "en1"},
    )
    assert intents.routable_tool_call({**base, "actions": [{"verb": "escape_grapple", "target_id": "en1"}]}) == (
        "escape_grapple",
        {"character_id": "ch_hero", "holder_id": "en1"},
    )
    assert intents.routable_tool_call({**base, "actions": [{"verb": "escape_grapple", "skill": "acrobatics"}]}) == (
        "escape_grapple",
        {"character_id": "ch_hero", "skill": "acrobatics"},
    )
    assert intents.routable_tool_call({**base, "actions": [{"verb": "grapple", "target_id": None}]}) is None
