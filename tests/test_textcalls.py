# ruff: noqa: E501 — образец ответа модели: длинные строки как есть
"""Текстовые псевдовызовы: фаза решения отклоняет, повествование не показывает игрокам."""

import asyncio
import random

from app.agents import textcalls
from app.db.models import Event, MasterTurn
from tests.game import party
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401

SAMPLE = """Иван сосредотачивает свои чувства. Мавзолей впереди источает ауру.

action: enter_room(room_id='loc_cemetery', party_ids=['ch_1'])
action: create_location(location_id='loc_crypt', name='Вход в склеп (старый)', parent_id='loc_cemetery', secret=False, link_to=[{'to_id': 'loc_cemetery', 'name': 'Кладбище'}])
action: spawn_entity(template_id='monster.skeleton', name='Скелет 1', disposition='hostile', cell=(15, 20))
Скелеты скрежещут костями.

***

Выполняю действия:
* `advance_plot(node_id='node_cemetery', outcome='done')`
* `describe_place(place_id='en_1', description='Площадка перед мавзолеем.',
  exits=[{'direction': 'west', 'description': 'Тропа к городу'}])`
"""


def test_parse_python_style_calls():
    names = textcalls.tool_names()
    calls = textcalls.parse(SAMPLE, names)
    assert [n for n, _ in calls] == [
        "enter_room",
        "create_location",
        "spawn_entity",
        "advance_plot",
        "describe_place",
    ]
    spawn = calls[2][1]
    assert spawn["cell"] == [15, 20] and spawn["disposition"] == "hostile"
    assert calls[1][1]["link_to"] == [{"to_id": "loc_cemetery", "name": "Кладбище"}]
    assert calls[1][1]["secret"] is False
    assert textcalls.parse('roll_check({"a": 1})', names) == []  # позиционный аргумент — не вызов
    assert textcalls.parse("Он сказал: unknown_tool(x=1)", names) == []


def test_strip_leaves_only_story():
    out = textcalls.clean(SAMPLE)
    assert out == ("Иван сосредотачивает свои чувства. Мавзолей впереди источает ауру.\n\nСкелеты скрежещут костями.")
    plain = "Действия героев были смелыми: Бран (молча) шагнул вперёд.\n\n***\n\nТишина."
    assert textcalls.clean(plain) == plain  # без вызовов текст не трогаем


def test_stream_filter_hides_calls_in_any_chunking():
    for seed in range(40):
        rnd = random.Random(seed)
        out: list[str] = []

        async def push(chunk, out=out):
            out.append(chunk)

        async def feed(rnd=rnd):
            f = textcalls.StreamFilter(push)
            i = 0
            while i < len(SAMPLE):
                n = rnd.randint(1, 15)
                await f(SAMPLE[i : i + n])
                i += n

        asyncio.run(feed())
        text = "".join(out)
        assert "_" not in text and "Выполняю" not in text and "(" not in text, text
        assert text.startswith("Иван сосредотачивает") and "Скелеты скрежещут костями." in text


def test_decide_requires_native_calls_for_text_attempts(game_client, admin_g, llm, dice, settings):  # noqa: F811
    c, (p1,), hero = party(game_client, admin_g)
    dice += [14]
    llm.replies += [
        {
            "text": (
                "Выполняю действия:\n* `roll_check(character_id='"
                + hero["id"]
                + "', stat='athletics', difficulty='dc.medium', reason='дверь')`"
            )
        },
        {
            "tool_calls": [
                (
                    "roll_check",
                    {"character_id": hero["id"], "stat": "athletics", "difficulty": "dc.medium", "reason": "дверь"},
                )
            ]
        },
        DONE,
        {
            "text": "Бран вышибает дверь.\naction: spawn_entity(template_id='monster.skeleton', name='Скелет')\n"
            "За дверью темно."
        },
    ]
    n = act(game_client, p1, c["id"], "Вышибаю дверь плечом")
    assert n["content"].endswith("вышибает дверь.\nЗа дверью темно.") and "spawn_entity" not in n["content"]
    # Текстовый вызов НЕ исполняется: реальный бросок — только из native tool_call.
    assert len(rows(settings, Event, Event.tool == "roll_check")) == 1
    note = llm.requests[1]["messages"][-1]["content"]
    assert "НЕ выполнил" in note and "настоящими tool_calls" in note

    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["closed"] == [hero["id"]]
    assert turn.trace["text_call_rejections"] == 1
    assert not any(t.get("from_text") for t in turn.trace["calls"])
    assert turn.trace["audit"]["tool_text"] == ["spawn_entity"]
    assert rows(settings, Event, Event.tool == "spawn_entity") == []


def test_combat_without_enemies_is_refused(game_client, admin_g, llm, settings):  # noqa: F811
    """Скелеты были только в тексте мастера: бой без врагов не начинается, а не кончается тут же «победой»."""
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [
        {"tool_calls": [("set_scene_mode", {"mode": "combat"})]},
        {"tool_calls": [("cancel_action", {"character_id": hero["id"], "reason": "врагов нет"})]},
        DONE,
        {"text": "Вокруг тихо."},
    ]
    act(game_client, p1, c["id"], "Атакую скелетов")
    tool_msg = next(m for m in llm.requests[1]["messages"] if m["role"] == "tool")
    assert "в бою нет врагов" in tool_msg["content"]
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["combat"] == []


MARKDOWN_CALLS = """<center>
[spawn_entity](template_id="creature.skeleton", location="en_room", position={"cell":{"x":2,"y":2}}, name="Скелет 1")
[spawn_entity](template_id="creature.skeleton", location="en_room", position={"cell":{"x":3,"y":1}}, name="Скелет 2")
[resolve_attack](attacker="ch_hero", target="en_foe", weapon="inv_sword")
</center>
Кости звенят в пустом зале.
"""


def test_markdown_calls_are_detected_and_removed():
    names = textcalls.tool_names()
    calls = textcalls.parse(MARKDOWN_CALLS, names)
    assert [name for name, _ in calls] == ["spawn_entity", "spawn_entity", "resolve_attack"]
    assert calls[0][1]["position"] == {"cell": {"x": 2, "y": 2}}
    assert textcalls.clean(MARKDOWN_CALLS) == "Кости звенят в пустом зале."
    assert textcalls.contains(r"\[spawn_entity\]\(name='Скелет')", names)
    assert textcalls.clean(r"\<center>" + "\n" + r"\[spawn_entity\]\(name='Скелет')" + "\n" + r"\</center>") == ""
    assert textcalls.clean("[spawn_entity](name='Незаконченный'") == ""


def test_markdown_calls_never_leak_into_stream():
    for seed in range(35):
        rnd = random.Random(seed)
        chunks: list[str] = []

        async def push(chunk, chunks=chunks):
            chunks.append(chunk)

        async def feed(rnd=rnd):
            stream = textcalls.StreamFilter(push)
            offset = 0
            while offset < len(MARKDOWN_CALLS):
                step = rnd.randint(1, 11)
                await stream(MARKDOWN_CALLS[offset : offset + step])
                offset += step

        asyncio.run(feed())
        public = "".join(chunks)
        assert "spawn_entity" not in public
        assert "resolve_attack" not in public
        assert "<center>" not in public
        assert "creature.skeleton" not in public
        assert "Кости звенят" in public


def test_master_rejects_markdown_commands_and_regenerates_story(game_client, admin_g, llm, settings):  # noqa: F811
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [
        {"text": MARKDOWN_CALLS},
        {"tool_calls": [("cancel_action", {"character_id": hero["id"], "reason": "действие непонятно"})]},
        DONE,
        {"text": MARKDOWN_CALLS.split("Кости звенят")[0]},
        {"text": "Бран заглядывает в пустую комнату."},
    ]
    n = act(game_client, p1, c["id"], "Оглядываюсь по сторонам")
    assert "Бран" in n["content"] and n["content"].endswith("заглядывает в пустую комнату.")
    assert "spawn_entity" not in n["content"]
    assert rows(settings, Event, Event.tool == "spawn_entity") == []
    assert rows(settings, Event, Event.tool == "resolve_attack") == []
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["text_call_rejections"] == 1
    assert turn.trace["audit"]["regenerated"]
    assert "spawn_entity" in turn.trace["audit"]["tool_text"]
