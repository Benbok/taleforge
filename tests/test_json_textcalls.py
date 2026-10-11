"""JSON pseudo calls never reach players or authorize world changes."""

import asyncio

import pytest

from app.agents import textcalls
from app.db.models import Event, MasterTurn
from tests.game import party
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401

CALLS = """[
  {"call": "describe_place", "args": {"id": "en_docks", "description": "Доки"}},
  {"call": "spawn_entity", "args": {"template_id": "npc_harbor_master", "position": {"x": 50}}}
]"""


@pytest.mark.parametrize(
    "payload",
    [
        CALLS,
        "```json\n" + CALLS + "\n```",
        "```json " + CALLS.replace("\n", " ") + " ```",
        CALLS[:-3],
        r"\`\`\`json" + "\n" + CALLS + "\n" + r"\`\`\`",
    ],
)
def test_json_pseudo_calls_are_detected_and_removed(payload):
    text = "В порту пахнет рыбой.\n\n" + payload
    assert textcalls.contains(text, textcalls.tool_names())
    assert textcalls.clean(text) == "В порту пахнет рыбой."


def test_json_pseudo_calls_are_parsed_for_audit_only():
    assert textcalls.parse(CALLS, textcalls.tool_names()) == [
        ("describe_place", {"id": "en_docks", "description": "Доки"}),
        ("spawn_entity", {"template_id": "npc_harbor_master", "position": {"x": 50}}),
    ]
    ordinary = 'На листке написано: {"name": "Элрик", "count": 2}.\nОбычный текст.'
    assert textcalls.clean(ordinary) == ordinary
    nested = '[{"ordinary":{"name":"spawn_entity"}}]'
    assert not textcalls.contains(nested, textcalls.tool_names())
    assert textcalls.clean(nested) == nested


@pytest.mark.parametrize(
    "payload",
    ['{"function":{"name":"get_scene"}}', '{"tool_calls":[{"type":"function","function":{"name":"get_scene"}}]}'],
)
def test_function_wrapper_without_arguments_is_still_a_command(payload):
    assert textcalls.contains(payload, textcalls.tool_names())
    assert textcalls.clean(payload) == ""
    assert textcalls.parse(payload, textcalls.tool_names()) == [("get_scene", {})]
    ordinary = '{"name":"get_scene"}'
    assert not textcalls.contains(ordinary, textcalls.tool_names())
    assert textcalls.clean(ordinary) == ordinary


@pytest.mark.parametrize("width", [1, 7, 40, 1000])
@pytest.mark.parametrize("payload", [CALLS, CALLS[:-3], '[\n  {"call": "spawn_ent', '{"name":"spawn_ent'])
def test_stream_never_publishes_json_pseudo_calls(width, payload):
    out = []

    async def feed():
        async def push(chunk):
            out.append(chunk)

        stream = textcalls.StreamFilter(push)
        text = "Доки затихли.\n```json\n" + payload
        for start in range(0, len(text), width):
            await stream(text[start : start + width])
        await stream.finish()

    asyncio.run(feed())
    assert "".join(out).strip() == "Доки затихли."


def test_decide_retries_json_without_executing_it(game_client, admin_g, llm, settings):  # noqa: F811
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [
        {"text": CALLS},
        {"tool_calls": [("auto_success", {"character_id": hero["id"], "reason": "Смотрит на воду"})]},
        DONE,
        {"text": "Вода спокойна.\n```json\n" + CALLS + "\n```"},
    ]
    n = act(game_client, p1, c["id"], "Смотрю на воду")
    assert n["content"] == "Вода спокойна."
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["text_call_rejections"] == 1
    assert turn.trace["audit"]["tool_text"] == ["describe_place", "spawn_entity"]
    assert not rows(settings, Event, Event.tool.in_(["describe_place", "spawn_entity"]))


def test_old_json_pseudo_calls_are_removed_from_history():
    from app.agents.master.helpers import _render_history
    from app.db.models import Message

    out = _render_history([Message(kind="narration", content="Тихо.\n" + CALLS)], {}, {})
    assert out == "[мастер] Тихо."


def test_story_feed_holds_json_before_tool_key_is_complete():
    from app.agents.prelude import StoryFeed

    shown, voiced = [], []

    class Stream:
        async def push(self, chunk):
            shown.append(chunk)

        async def reset(self):
            raise AssertionError("An unsafe draft must never require a reset")

    class Voice:
        def feed(self, chunk):
            voiced.append(chunk)

    async def feed():
        out = StoryFeed(Stream(), Voice())
        await out.push('Доки затихли.\n[\n {"ca')
        assert "".join(shown).strip() == "Доки затихли."
        assert '"ca' not in "".join(voiced)
        await out.push('ll": "spawn_entity", "args": {}}]')
        assert "".join(shown).strip() == "Доки затихли."

    asyncio.run(feed())
