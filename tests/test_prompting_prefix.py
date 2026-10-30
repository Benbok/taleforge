import json
from copy import deepcopy

from app.agents.master.prompting.messages import cacheable, decide_messages, request_size


def test_system_message_and_tools_are_identical_between_turns():
    first = decide_messages({"source": "иду", "scene": {}})
    second = decide_messages({"source": "жду", "scene": {}}, "исправь")
    assert first[0] == second[0]
    assert "capabilities" not in json.loads(first[1]["content"])
    assert "capabilities" in first[0]["content"]


def test_repair_goes_last_in_the_user_message():
    messages = decide_messages({"source": "иду", "scene": {}, "repair": "stale"}, "fix")
    data = json.loads(messages[-1]["content"])
    assert list(data)[-1] == "repair"
    assert data["repair"] == "fix"


def test_cache_marker_only_for_anthropic_models():
    original = decide_messages({"source": "иду", "scene": {}})
    saved = deepcopy(original)
    assert cacheable(original, "deepseek/deepseek-flash") == original
    for model in ("anthropic/claude-sonnet-4", "claude-test"):
        marked = cacheable(original, model)
        assert marked[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
        assert marked[0]["content"][0]["text"] == original[0]["content"]
        assert marked[1:] == original[1:]
        assert request_size(marked, {}) == request_size(original, {})
    assert original == saved
