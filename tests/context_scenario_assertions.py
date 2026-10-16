"""Independent assertions for executable context-quality scenarios."""

from __future__ import annotations

from collections.abc import Iterable

from tests.context_scenario_worlds import ScenarioResult


def _contains_all(haystacks: Iterable[str], needles: Iterable[str]) -> None:
    text = "\n".join(haystacks)
    for needle in needles:
        assert needle in text, f"expected marker is absent from recorded output: {needle!r}"


def assert_scenario(case: dict, result: ScenarioResult) -> None:
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

    all_prompt_text = "\n".join(packet.get("content", "") for packet in result.prompt_packets)
    prompt_text = {role: all_prompt_text for role in ("decide", "narrate", "voice")}
    for role, required in (case.get("required_facts_by_role") or {}).items():
        if "request" in required:
            _contains_all((prompt_text.get(role, ""),), result.requests)
    for role, forbidden in (case.get("forbidden_facts_by_role") or {}).items():
        content = prompt_text.get(role, "")
        for marker in forbidden:
            assert marker not in content, f"forbidden marker leaked into {role}: {marker!r}"

    assert result.refs, "scenario did not persist any message/event reference"

