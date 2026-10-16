"""Real gateway-backed scenario runner used by context-quality tests."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.agents.llm import ScriptedLLM
from app.db.models import Campaign, Entity, Event, MasterTurn, Message
from app.tools.registry import execute
from app.tools.runtime import flush_outbox, open_context
from tests.conftest import login
from tests.game import FIGHTER, QueueDice, import_base, ok, party, quiet, run
from tests.test_ws import connect


@dataclass
class ScenarioWorld:
    campaign_id: str
    actors: dict[str, dict[str, Any]]
    entity_aliases: dict[str, str]
    client: Any
    settings: Any
    llm: ScriptedLLM
    parser_script: str
    model_script: str
    dice: list[int]


@dataclass(frozen=True)
class ScenarioResult:
    case_id: str
    events: tuple[dict[str, Any], ...]
    messages: tuple[str, ...]
    refs: tuple[str, ...]
    world: dict[str, Any]
    requests: tuple[str, ...]
    prompt_packets: tuple[dict[str, Any], ...]
    turns: tuple[str, ...] = ()
    rejections: tuple[dict[str, Any], ...] = ()


def _admin(client) -> dict[str, str]:
    root = login(client, "root", "rootpass")
    name = f"scenario-{uuid.uuid4().hex[:8]}"
    response = client.post("/api/admin/users", json={"name": name, "password": "secret1"}, headers=root)
    assert response.status_code == 201, response.text
    return login(client, name, "secret1")


def _assert_case_input(case: dict) -> None:
    if "expected_outcomes" in case:
        raise ValueError("expected_outcomes is an oracle/input coupling; use expected_world")
    if not isinstance(case.get("requests"), list) or not all(isinstance(item, dict) for item in case["requests"]):
        raise ValueError("scenario fixture requires request objects with actor and text")


def build_scenario(case_id: str, client, settings, *, case: dict | None = None) -> ScenarioWorld:
    """Create a fresh campaign and deterministic actors without using expected output as input."""
    if case is None:
        raise ValueError("build_scenario requires a manifest case")
    _assert_case_input(case)
    if case["id"] != case_id:
        raise ValueError(f"fixture id mismatch: {case_id!r} != {case['id']!r}")

    import_base(settings)
    admin = _admin(client)
    players = 2 if any(req["actor"] in {"hero_a", "hero_b"} for req in case["requests"]) else 1
    campaign, heads, first_hero = party(client, admin, players=players, start=False)
    heroes = {"hero": first_hero, "hero_a": first_hero}
    if players == 2:
        second = ok(
            client.post(
                f"/api/campaigns/{campaign['id']}/characters",
                json={**FIGHTER, "name": "Гимли"},
                headers=heads[1],
            ),
            201,
        )
        ok(client.post(f"/api/campaigns/{campaign['id']}/characters/{second['id']}/submit", headers=heads[1]))
        heroes["hero_b"] = second
    ok(client.post(f"/api/campaigns/{campaign['id']}/session/start", headers=admin))
    quiet(client)

    aliases: dict[str, str] = {}
    if case_id == "combat_effect" or case_id == "multipart":
        aliases.update(_setup_combat(settings, campaign["id"], first_hero["id"]))

    llm = client.app.state.master.llm
    return ScenarioWorld(
        campaign_id=campaign["id"],
        actors={
            name: {"id": hero["id"], "headers": heads[0 if name != "hero_b" else 1]}
            for name, hero in heroes.items()
        },
        entity_aliases=aliases,
        client=client,
        settings=settings,
        llm=llm,
        parser_script=case["parser_script"],
        model_script=case["model_script"],
        dice=list(case.get("dice") or []),
    )


def _setup_combat(settings, campaign_id: str, hero_id: str) -> dict[str, str]:
    async def prepare(session):
        campaign = await session.get(Campaign, campaign_id)
        ctx = await open_context(session, campaign, QueueDice([]), turn_id="scenario-setup", seat_id=None)
        spawned = await execute(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Сценарный гоблин", "zone": "melee"},
        )
        assert spawned["ok"], spawned
        enemy = spawned["result"]["spawned"][0]["id"]
        weapon = next(item.id for item in ctx.world.inventory[hero_id] if item.item_template_id == "item.longsword")
        await flush_outbox(session, ctx)
        await session.commit()
        return {"enemy": enemy, "weapon": weapon}

    return run(settings, prepare)


def _parser_reply(world: ScenarioWorld, script: str, actor_id: str) -> dict:
    if script == "unknown_parser":
        return {}
    if script == "speech_npc":
        return {"kind": "speech", "speech": "Добрый день, хозяин таверны.", "actions": [], "confidence": 1.0}
    if script in {"combat_effect", "multipart"}:
        action = {
            "verb": "attack",
            "target_id": world.entity_aliases["enemy"],
            "instrument_id": world.entity_aliases["weapon"],
        }
    else:
        action = {"verb": "interact", "summary": f"scenario:{script}"}
    return {"kind": "action", "character_id": actor_id, "actions": [action], "confidence": 1.0, "problem": "none"}


def _install_script(world: ScenarioWorld) -> None:
    llm = world.llm
    original = llm.complete
    case_id = world.model_script

    async def complete(messages, **kwargs):
        names = {tool["function"]["name"] for tool in kwargs.get("tools") or []}
        if "submit_intent" in names:
            actor_id = next(iter(world.actors.values()))["id"]
            reply = {"tool_calls": [("submit_intent", _parser_reply(world, world.parser_script, actor_id))]}
        elif "submit_summary" in names:
            reply = {
                "tool_calls": [
                    (
                        "submit_summary",
                        {"events": [f"SCENARIO_OUTCOME:{case_id}"], "recap": f"SCENARIO_OUTCOME:{case_id}"},
                    )
                ]
            }
        elif "write_chronicle" in names:
            reply = {"tool_calls": [("write_chronicle", {"notes": []})]}
        elif names:
            reply = {"text": "готово"}
        else:
            reply = {"text": f"SCENARIO_OUTCOME:{case_id}"}
        llm.replies.insert(0, reply)
        return await original(messages, **kwargs)

    llm.complete = complete


def _receive_until(ws, client, predicate, timeout_s: float = 10.0) -> list[dict[str, Any]]:
    from tests.test_ws import _receive_json_with_deadline

    events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        event = client.portal.call(_receive_json_with_deadline, ws, max(0.1, deadline - time.monotonic()))
        events.append(event)
        if predicate(event):
            return events
    raise TimeoutError("scenario gateway did not produce a terminal event")


def run_scenario(case: dict, world: ScenarioWorld, client, llm) -> ScenarioResult:
    """Send every request via WebSocket and collect persisted production records."""
    _assert_case_input(case)
    assert llm is world.llm
    _install_script(world)
    all_events: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    requests = tuple(item["text"] for item in case["requests"])
    for index, item in enumerate(case["requests"]):
        actor = world.actors[item["actor"]]
        with connect(client, actor["headers"], world.campaign_id) as (ws, _):
            client_id = f"scenario:{case['id']}:{index}"
            request_text = item["text"]
            ws.send_json(
                {
                    "type": "message.send",
                    "payload": {"kind": "action", "text": request_text, "client_id": client_id},
                }
            )
            accepted = _receive_until(
                ws,
                client,
                lambda event, expected_text=request_text: event.get("type") == "message.rejected"
                or (
                    event.get("type") == "message.new"
                    and event.get("payload", {}).get("kind") in {"action", "speech", "question"}
                    and event.get("payload", {}).get("content") == expected_text
                ),
            )
            events = list(accepted)
            if accepted[-1].get("type") == "message.new":
                events.extend(
                    _receive_until(
                        ws,
                        client,
                        lambda event: event.get("type") == "message.new"
                        and event.get("payload", {}).get("kind") == "narration",
                    )
                )
            all_events.extend(events)
            rejections.extend(event for event in events if event.get("type") == "message.rejected")
    client.portal.call(client.app.state.master.wait_idle, world.campaign_id)
    persisted = _persisted(world.settings, world.campaign_id)
    prompt_packets = tuple(
        packet
        for request in (*llm.requests, *llm.parser_requests)
        for packet in request.get("messages", [])
    )
    return ScenarioResult(
        case_id=case["id"],
        events=tuple(persisted["events"]),
        messages=tuple(persisted["messages"]),
        refs=tuple(persisted["refs"]),
        world=persisted["world"],
        requests=requests,
        prompt_packets=prompt_packets,
        turns=tuple(persisted["turns"]),
        rejections=tuple(rejections),
    )


def _persisted(settings, campaign_id: str) -> dict[str, Any]:
    async def read(session):
        messages = (
            await session.scalars(select(Message).where(Message.campaign_id == campaign_id).order_by(Message.seq))
        ).all()
        events = (await session.scalars(select(Event).where(Event.campaign_id == campaign_id))).all()
        turns = (await session.scalars(select(MasterTurn).where(MasterTurn.campaign_id == campaign_id))).all()
        entities = (await session.scalars(select(Entity).where(Entity.campaign_id == campaign_id))).all()
        return {
            "messages": [message.content for message in messages],
            "refs": [message.id for message in messages] + [event.id for event in events],
            "events": [{"id": event.id, "tool": event.tool, "payload": event.payload} for event in events],
            "turns": [turn.id for turn in turns if turn.status == "done"],
            "world": {entity.id: dict(entity.state or {}) for entity in entities},
        }

    return run(settings, read)

