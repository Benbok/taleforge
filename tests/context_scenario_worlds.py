"""Real gateway-backed scenario runner used by context-quality tests."""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.agents.llm import ScriptedLLM
from app.db.models import Message
from tests.conftest import login
from tests.context_scenario_setups import read_state, setup_world
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
    active_request: dict = field(default_factory=dict)
    packets: list = field(default_factory=list)
    baseline: dict = field(default_factory=dict)
    observations: dict = field(default_factory=dict)


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

    llm = client.app.state.master.llm
    world = ScenarioWorld(
        campaign_id=campaign["id"],
        actors={
            name: {"id": hero["id"], "headers": heads[0 if name != "hero_b" else 1]} for name, hero in heroes.items()
        },
        entity_aliases={},
        client=client,
        settings=settings,
        llm=llm,
        parser_script=case["parser_script"],
        model_script=case["model_script"],
        dice=list(case.get("dice") or []),
    )
    world.entity_aliases = setup_world(settings, world.campaign_id, world.actors, case_id)
    world.baseline = _persisted(settings, world.campaign_id)
    return world


def _parser_reply(world: ScenarioWorld, script: str, actor_id: str) -> dict:
    if script == "unknown_parser":
        return {}
    if script == "speech_npc":
        return {"kind": "speech", "speech": "Добрый день, хозяин таверны.", "actions": [], "confidence": 1.0}
    if script == "combat_effect":
        action = {
            "verb": "attack",
            "target_id": world.entity_aliases["enemy"],
            "instrument_id": world.entity_aliases["weapon"],
        }
    elif script == "transition":
        action = {"verb": "move", "target_id": world.entity_aliases["docks"]}
    elif script == "hidden_search":
        action = {"verb": "search", "summary": "Осмотреть тайник"}
    else:
        target = "npc_b" if script == "split_party" and world.active_request["actor"] == "hero_b" else "npc"
        action = {"verb": "persuade", "target_id": world.entity_aliases[target]}
    actions = [action]
    if script == "multipart":
        actions = [
            {"verb": "search", "target_id": world.entity_aliases[alias]} for alias in ("first_chest", "second_chest")
        ]
    return {"kind": "action", "character_id": actor_id, "actions": actions, "confidence": 1.0, "problem": "none"}


@contextmanager
def _install_script(world: ScenarioWorld):
    llm = world.llm
    original = llm.complete
    master = world.client.app.state.master
    original_ask = master._ask
    original_dice = master.dice_factory
    purpose = ContextVar("scenario_purpose", default=None)
    stages = {}
    master.dice_factory = lambda: QueueDice(world.dice)
    case_id = world.model_script

    async def ask(*args, **kwargs):
        role = args[5] if len(args) > 5 else kwargs["purpose"]
        messages = args[6] if len(args) > 6 else kwargs["messages"]
        token = purpose.set(role)
        world.packets.append(
            {
                "purpose": role,
                "messages": deepcopy(messages),
                "request": world.active_request.get("text"),
                "metadata": deepcopy(kwargs.get("prompt_metadata") or {}),
                "actor_id": world.actors[world.active_request["actor"]]["id"],
            }
        )
        try:
            return await original_ask(*args, **kwargs)
        finally:
            purpose.reset(token)

    async def complete(messages, **kwargs):
        names = {tool["function"]["name"] for tool in kwargs.get("tools") or []}
        if "submit_intent" in names:
            actor_id = world.actors[world.active_request["actor"]]["id"]
            world.packets.append({"purpose": "parse", "messages": deepcopy(messages), "actor_id": actor_id})
            attempt = sum(p["purpose"] == "parse" for p in world.packets)
            mode = world.observations.get("parser_failure", "empty")
            recovered = world.observations.get("recover_success") and attempt > 1
            if world.parser_script == "unknown_parser" and not recovered:
                if mode == "error":
                    from app.agents.llm import LLMError

                    raise LLMError("scenario parser error")
                if mode == "timeout":
                    raise TimeoutError("scenario parser timeout")
            script = "old_promise" if recovered else world.parser_script
            reply = {"tool_calls": [("submit_intent", _parser_reply(world, script, actor_id))]}
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
        elif purpose.get() == "decide":
            index = world.active_request["index"]
            stage = stages.get(index, 0)
            stages[index] = stage + 1
            reply = await _decision(world, stage)
        elif purpose.get() == "narrate" and case_id == "resume" and not world.observations.get("resuming"):
            from app.agents.llm import LLMError

            raise LLMError("scenario interrupted after effects committed")
        elif names:
            reply = {"text": "готово"}
        else:
            reply = {"text": f"SCENARIO_OUTCOME:{case_id}"}
        llm.replies.insert(0, reply)
        return await original(messages, **kwargs)

    llm.complete = complete
    master._ask = ask
    try:
        yield
    finally:
        llm.complete = original
        master._ask = original_ask
        master.dice_factory = original_dice


async def _decision(world, stage):
    """Issue real commands, with references read from the persisted source message."""
    if stage:
        return {"text": "готово"}
    actor = world.actors[world.active_request["actor"]]["id"]
    aliases = world.entity_aliases
    family = world.model_script
    async with world.client.app.state.sessionmaker() as s:
        message = (
            await s.scalars(
                select(Message)
                .where(Message.campaign_id == world.campaign_id, Message.content == world.active_request["text"])
                .order_by(Message.seq.desc())
            )
        ).first()
        assert message is not None
        from app.core.resolution.contracts import ActionRef

        # Binding is still inside the active turn transaction. Use the committed source identity
        # and the parser's parts; production validates these against its own bound action list.
        actions = (message.intent or {}).get("actions", [])
        refs = [
            ActionRef(
                campaign_id=world.campaign_id, source_kind="message", source_id=message.id, actor_id=actor, part=i
            ).model_dump()
            for i in range(len(actions))
        ]
    ref = refs[0] if refs else None
    if family == "speech_npc":
        return {"text": "готово"}
    if family == "combat_effect":
        return {
            "tool_calls": [
                (
                    "resolve_attack",
                    {
                        "attacker_id": actor,
                        "target_id": aliases["enemy"],
                        "attack": aliases["weapon"],
                        "action_ref": ref,
                    },
                )
            ]
        }
    if family == "multipart":
        commands = []
        for index, alias in enumerate(("first_chest", "second_chest")):
            commands.extend(
                [
                    (
                        "roll_check",
                        {
                            "character_id": actor,
                            "stat": "investigation",
                            "target_id": aliases[alias],
                            "difficulty": "dc.easy",
                            "reason": "осмотр сундука",
                            "action_ref": refs[index],
                        },
                    ),
                    (
                        "reveal_knowledge",
                        {
                            "character_id": actor,
                            "entity_id": aliases[alias],
                            "level": 2,
                            "discovered": True,
                            "action_ref": refs[index],
                        },
                    ),
                ]
            )
        return {"tool_calls": commands}
    if family == "transition":
        args = {"character_ids": [actor], "location_id": aliases["docks"], "action_ref": ref}
        return {"tool_calls": [("move", args)]}
    if family == "hidden_search":
        return {
            "tool_calls": [
                (
                    "roll_check",
                    {
                        "character_id": actor,
                        "stat": "perception",
                        "difficulty": "dc.easy",
                        "reason": "осмотр тайника",
                        "action_ref": ref,
                    },
                ),
                (
                    "reveal_knowledge",
                    {
                        "character_id": actor,
                        "entity_id": aliases["cache"],
                        "level": 2,
                        "discovered": True,
                        "action_ref": ref,
                    },
                ),
            ]
        }
    npc = aliases["npc_b"] if family == "split_party" and world.active_request["actor"] == "hero_b" else aliases["npc"]
    commands = [
        (
            "roll_check",
            {
                "character_id": actor,
                "stat": "persuasion",
                "target_id": npc,
                "difficulty": "dc.easy",
                "reason": "разговор",
                "action_ref": ref,
            },
        )
    ]
    if family == "two_heroes" and world.active_request["actor"] == "hero_b":
        async with world.client.app.state.sessionmaker() as s:
            first = (
                await s.scalars(
                    select(Message)
                    .where(Message.campaign_id == world.campaign_id, Message.kind == "action")
                    .order_by(Message.seq)
                )
            ).first()
            foreign = dict(first.data["resolution_actions"][0]["ref"], actor_id=actor)
        commands.insert(0, ("roll_check", {**commands[0][1], "action_ref": foreign}))
    if family in {"npc_motive", "old_promise", "resume"}:
        commands.append(("update_entity", {"entity_id": aliases["npc"], "mood": "SCENARIO_KEEPER_LISTENED"}))
    if family == "world_reaction":
        commands.extend(
            [
                ("update_entity", {"entity_id": aliases["npc"], "mood": "SCENARIO_OBLIGATION_FULFILLED"}),
                ("resolve_response", {"response_id": "scenario-response", "how": "SCENARIO_OBLIGATION_FULFILLED"}),
            ]
        )
    return {"tool_calls": commands}


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
    with _install_script(world):
        return _run_scenario(case, world, client, llm)


def _run_scenario(case: dict, world: ScenarioWorld, client, llm) -> ScenarioResult:
    """Send every request via WebSocket and collect persisted production records."""
    _assert_case_input(case)
    assert llm is world.llm
    all_events: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    requests = tuple(item["text"] for item in case["requests"])
    for index, item in enumerate(case["requests"]):
        world.active_request = {**item, "index": index}
        actor = world.actors[item["actor"]]
        with connect(client, actor["headers"], world.campaign_id) as (ws, _):
            world.observations.setdefault("initial_snapshots", []).append(deepcopy(_))
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
                lambda event, expected_text=request_text: (
                    event.get("type") == "message.rejected"
                    or (
                        event.get("type") == "message.new"
                        and event.get("payload", {}).get("kind") in {"action", "speech", "question"}
                        and event.get("payload", {}).get("content") == expected_text
                    )
                ),
            )
            events = list(accepted)
            if accepted[-1].get("type") == "message.new":
                events.extend(
                    _receive_until(
                        ws,
                        client,
                        lambda event: (
                            event.get("type") == "message.new"
                            and (
                                event.get("payload", {}).get("kind") == "narration"
                                or (
                                    event.get("payload", {}).get("kind") == "system"
                                    and "сохранен" in event.get("payload", {}).get("content", "")
                                )
                            )
                        ),
                    )
                )
            all_events.extend(events)
            rejections.extend(event for event in events if event.get("type") == "message.rejected")
    client.portal.call(client.app.state.master.wait_idle, world.campaign_id)
    if case["id"] == "resume":
        interrupted = _persisted(world.settings, world.campaign_id)
        failed = [t for t in interrupted["world"]["turn_rows"] if t["status"] == "failed"]
        assert len(failed) == 1, interrupted["world"]["turn_rows"]
        world.observations["interrupted"] = interrupted
        world.observations["resuming"] = True
        assert client.portal.call(client.app.state.master.reopen_narration, world.campaign_id, failed[0]["id"])
        quiet(client)
    persisted = _persisted(world.settings, world.campaign_id)
    if case["id"] == "hidden_search":
        with connect(client, world.actors["hero"]["headers"], world.campaign_id) as (_, snapshot):
            world.observations["discovered_snapshot"] = snapshot
    persisted["world"].update(
        aliases=world.entity_aliases,
        actors=world.actors,
        baseline=world.baseline,
        observations=world.observations,
        dice_remaining=list(world.dice),
    )
    prompt_packets = tuple(world.packets)
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
    return run(settings, lambda s: read_state(s, campaign_id))
