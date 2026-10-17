"""Independent assertions for executable context-quality scenarios."""

from __future__ import annotations

from collections.abc import Iterable

from tests.context_scenario_worlds import ScenarioResult


def _contains_all(haystacks: Iterable[str], needles: Iterable[str]) -> None:
    text = "\n".join(haystacks)
    for needle in needles:
        assert needle in text, f"expected marker is absent from recorded output: {needle!r}"


def assert_scenario(case: dict, result: ScenarioResult, *, check_context_diagnostics: bool = True) -> None:
    """Check persisted effects and captured prompts; never manufacture inputs."""
    assert result.case_id == case["id"]
    assert result.requests == tuple(request["text"] for request in case["requests"])

    expected = case.get("expected_world") or {}
    _contains_all(result.messages, expected.get("message_contains", ()))
    assert len(result.messages) >= int(expected.get("min_messages", 0))
    for path, expected_values in (expected.get("world_contains") or {}).items():
        actual = result.world.get(path, ())
        _contains_all(actual if isinstance(actual, (list, tuple, set)) else (str(actual),), expected_values)
    tools = {event.get("tool") for event in result.events if isinstance(event, dict)}
    assert set(expected.get("event_tools", ())) <= tools
    assert len(result.turns) >= int(expected.get("min_turns", 0))
    assert len(result.rejections) == int(expected.get("rejections", 0))

    prompt_text = {}
    for packet in result.prompt_packets:
        role = packet["purpose"]
        prompt_text.setdefault(role, [])
        prompt_text[role].extend(message.get("content") or "" for message in packet["messages"])
    required_roles = set(case.get("required_facts_by_role", {})) | set(case.get("forbidden_facts_by_role", {}))
    for role in required_roles:
        assert role in prompt_text, f"required role was never called: {role}"
    prompt_text = {role: "\n".join(parts) for role, parts in prompt_text.items()}
    for role, required in (case.get("required_facts_by_role") or {}).items():
        for marker in required:
            _contains_all((prompt_text[role],), result.requests if marker == "request" else (marker,))
    for role, forbidden in (case.get("forbidden_facts_by_role") or {}).items():
        content = prompt_text.get(role, "")
        for marker in forbidden:
            assert marker not in content, f"forbidden marker leaked into {role}: {marker!r}"

    assert result.refs, "scenario did not persist any message/event reference"
    if "baseline" in result.world:
        _assert_family(case, result, check_context_diagnostics=check_context_diagnostics)


def _assert_family(case, result, *, check_context_diagnostics=True):
    world = result.world
    baseline = world["baseline"]
    setup_ids = {event["id"] for event in baseline["events"]}
    events = [event for event in result.events if event["id"] not in setup_ids]
    family = case["id"]
    aliases, actors = world["aliases"], world["actors"]
    hero = actors["hero"]["id"]
    messages = [m for m in world["message_rows"] if m["content"] in result.requests]
    if family == "unknown_parser":
        assert len(messages) == len(result.requests)
        assert all(message["intent"].get("parser_fallback") for message in messages)
        assert sum(p["purpose"] == "parse" for p in result.prompt_packets) == 1
        return
    assert len(messages) == len(result.requests)
    for request, message in zip(case["requests"], messages, strict=True):
        assert message["seat_id"] == world["characters"][actors[request["actor"]]["id"]]["seat_id"]
        for part, entry in enumerate(message["data"].get("resolution_actions", [])):
            ref = entry["ref"]
            assert ref["source_id"] == message["id"] and ref["part"] == part
            assert ref["actor_id"] == actors[request["actor"]]["id"]
    tools = [event["tool"] for event in events]
    if family == "speech_npc":
        assert messages[0]["kind"] == "speech"
        assert not events, events
        assert world["entities"] == baseline["world"]["entities"]
        return
    assert "cancel_action" not in tools, world["turn_rows"]
    # Every mechanical action must have a successful, event-backed persisted result.
    for message in messages:
        progress = message["data"].get("resolution_progress", {})
        assert progress, message
        for part in progress.values():
            assert part["status"] == "completed", part
            assert part["result"]["event_ids"], part
            assert set(part["result"]["event_ids"]) <= {e["id"] for e in events}
    assert not world["dice_remaining"], world["dice_remaining"]
    if family == "hidden_search":
        import json

        assert "SCENARIO_HIDDEN_CACHE" not in json.dumps(world["observations"]["initial_snapshots"])
        assert "SCENARIO_HIDDEN_CACHE" in json.dumps(world["observations"]["discovered_snapshot"])
        assert tools.count("roll_check") == tools.count("reveal_knowledge") == 1
        assert any(
            k["character_id"] == hero and k["entity_id"] == aliases["cache"] and k["revealed"] and k["level"] == 2
            for k in world["knowledge"]
        )
        assert not any(k["entity_id"] == aliases["cache"] and k["revealed"] for k in baseline["world"]["knowledge"])
    elif family == "combat_effect":
        attack = next(e for e in events if e["tool"] == "resolve_attack")
        assert tools.count("resolve_attack") == 1
        assert attack["payload"]["mode"] == "disadvantage", attack
        assert attack["payload"]["natural"] == 12 and attack["payload"]["hit"]
        hp_before = baseline["world"]["entities"][aliases["enemy"]]["state"]["hp"]
        hp_after = world["entities"][aliases["enemy"]]["state"]["hp"]
        assert hp_after == max(0, hp_before - attack["payload"]["damage"])
        for key in ("hp", "slots_used", "hit_dice_used"):
            before = baseline["world"]["characters"][hero]["resources"]
            assert world["characters"][hero]["resources"].get(key) == before.get(key)
    elif family == "multipart":
        assert tools == ["roll_check", "reveal_knowledge", "roll_check", "reveal_knowledge"], events
        assert [e["target_id"] for e in events] == [aliases["first_chest"]] * 2 + [aliases["second_chest"]] * 2
        assert len(messages[0]["data"]["resolution_actions"]) == 2
        assert len(messages[0]["data"]["resolution_progress"]) == 2
        for alias in ("first_chest", "second_chest"):
            assert any(
                k["character_id"] == hero and k["entity_id"] == aliases[alias] and k["level"] == 2
                for k in world["knowledge"]
            )
    elif family == "transition":
        assert tools.count("move") == 1
        assert world["characters"][hero]["location_id"] == aliases["docks"]
        assert baseline["world"]["characters"][hero]["location_id"] == aliases["square"]
    elif family == "resume":
        interrupted = world["observations"]["interrupted"]
        assert {e["id"] for e in interrupted["events"]} == {e["id"] for e in result.events}
        assert interrupted["world"]["entities"] == world["entities"]
        assert len(world["turn_rows"]) == 1
        assert world["turn_rows"][0]["checkpoint"]["stage"] == "done"
    elif family == "world_reaction":
        if check_context_diagnostics:
            decisions = [p for p in result.prompt_packets if p["purpose"] == "decide"]
            assert any(
                any(reason.startswith("unknown_dependency:") for reason in p["metadata"].get("expansion_reasons", []))
                for p in decisions
            )
        assert tools.count("resolve_response") == 1
        assert world["scene"]["state"]["standing"]["responses"][0]["status"] == "done"
        assert world["entities"][aliases["npc"]]["state"]["mood"] == "SCENARIO_OBLIGATION_FULFILLED"
    elif family in {"old_promise", "npc_motive"}:
        assert tools.count("roll_check") == tools.count("update_entity") == 1
        assert world["entities"][aliases["npc"]]["state"]["mood"] == "SCENARIO_KEEPER_LISTENED"
    elif family in {"two_heroes", "split_party"}:
        assert {e["actor_id"] for e in events if e["tool"] == "roll_check"} == {
            actors["hero_a"]["id"],
            actors["hero_b"]["id"],
        }
        if family == "two_heroes":
            failures = [
                call["result"]
                for turn in world["turn_rows"]
                for call in turn["trace"].get("calls", [])
                if not call.get("result", {}).get("ok", True)
            ]
            assert any((failure.get("failure") or {}).get("code") == "invalid_source" for failure in failures), failures
        else:
            narration_ids = {t["narration_message_id"] for t in world["turn_rows"]}
            narrations = [m for m in world["message_rows"] if m["id"] in narration_ids]
            assert len(narrations) == 2
            for message in messages:
                seat = message["seat_id"]
                other = next(c["seat_id"] for c in world["characters"].values() if c["seat_id"] != seat)
                turn = next(t for t in world["turn_rows"] if t["id"] == message["turn_id"])
                narration = next(m for m in narrations if m["id"] == turn["narration_message_id"])
                assert seat in narration["visible_to"] and other not in narration["visible_to"], narration
                assert narration["data"]["place"] == message["data"]["scene_context"]["location_id"]
            for packet in result.prompt_packets:
                if packet["purpose"] != "narrate":
                    continue
                content = "\n".join(m.get("content") or "" for m in packet["messages"])
                forbidden = "DOCKS_ONLY_WITNESS" if packet["actor_id"] == hero else "SCENARIO_KEEPER"
                assert forbidden not in content, (forbidden, content)
