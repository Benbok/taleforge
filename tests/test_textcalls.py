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


# Ответ из живой кампании: модель вывела вызовы JSON-блоком, а не через function calling.
JSON_SAMPLE = """Он снова указывает тростью на север, в сторону складов. «Время тикает».

```json
[
  {"call": "describe_place", "args": {"id": "en_1", "description": "[[en_1|Грязные Доки]] — лабиринт причалов. К северу склад.", "coordinates": [50,50,0], "secret": false}},
  {"call": "add_landmark", "args": {"location_id": "en_1", "name": "Группа Складов", "kind": "building", "secret": false}}
]
```
"""


def test_json_calls_are_detected_parsed_and_removed():
    names = textcalls.tool_names()
    assert textcalls.contains(JSON_SAMPLE, names)
    calls = textcalls.parse(JSON_SAMPLE, names)
    assert [n for n, _ in calls] == ["describe_place", "add_landmark"]
    assert calls[1][1]["name"] == "Группа Складов" and calls[0][1]["secret"] is False
    assert textcalls.clean(JSON_SAMPLE) == "Он снова указывает тростью на север, в сторону складов. «Время тикает»."
    # другие формы: один объект без ограды, ключи tool/arguments и name/parameters
    bare = 'Тишина.\n{"tool": "add_landmark", "arguments": {"name": "Лавка"}}\nДождь.'
    assert textcalls.parse(bare, names) == [("add_landmark", {"name": "Лавка"})]
    assert textcalls.clean(bare) == "Тишина.\nДождь."
    named = '```\n{"name": "spawn_entity", "parameters": {"name": "Крыса"}}\n```\nКрыса пищит.'
    assert textcalls.parse(named, names) == [("spawn_entity", {"name": "Крыса"})]
    assert textcalls.clean(named) == "Крыса пищит."
    # обычный JSON и разметка в начале строки — не вызовы
    for plain in (
        "[[en_1|Грязные Доки]] — лабиринт причалов.",
        'Он прочёл: {"name": "Иван", "age": 3}.',
        "```\nстих\n```",
    ):
        assert not textcalls.contains(plain, names), plain
        assert textcalls.clean(plain) == plain


def test_stream_filter_hides_json_calls_in_any_chunking():
    for seed in range(40):
        rnd = random.Random(seed)
        out: list[str] = []

        async def push(chunk, out=out):
            out.append(chunk)

        async def feed(rnd=rnd):
            f = textcalls.StreamFilter(push)
            i = 0
            while i < len(JSON_SAMPLE):
                n = rnd.randint(1, 15)
                await f(JSON_SAMPLE[i : i + n])
                i += n
            await f.finish()

        asyncio.run(feed())
        text = "".join(out)
        assert "call" not in text and "```" not in text and "{" not in text, text
        assert text.startswith("Он снова указывает")


def test_autolink_unwraps_markup_without_id():
    from app.core.linker import autolink

    names = {"en_1": "Грязные Доки"}
    text = "Он указывает на [[Группа Складов]] и [[Грязные Доки]]."
    assert autolink(text, names) == "Он указывает на Группа Складов и [[en_1|Грязные Доки]]."


def test_decide_rejects_json_calls_and_asks_for_native(game_client, admin_g, llm, settings):  # noqa: F811
    """JSON-блок вместо tool_calls на фазе решения не исполняется: мастер получает просьбу повторить настоящими вызовами."""
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [
        {"text": JSON_SAMPLE},
        DONE,
        DONE,
        {"text": "Бран оглядывается."},
    ]
    n = act(game_client, p1, c["id"], "Оглядываюсь")
    assert n["content"].endswith("оглядывается.")
    note = llm.requests[1]["messages"][-1]["content"]
    assert "НЕ выполнил" in note
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["text_call_rejections"] == 1
    assert rows(settings, Event, Event.tool == "add_landmark") == []


def test_narration_rewrites_markup_of_unregistered_place(game_client, admin_g, llm, settings):  # noqa: F811
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [
        DONE,
        DONE,
        {"text": "Капитан указывает на [[Группа Складов]]."},
        {"text": "Капитан указывает на склады к северу."},
    ]
    n = act(game_client, p1, c["id"], "Куда идти?")
    assert n["content"] == "Капитан указывает на склады к северу."
    retry = next(r["messages"][-1]["content"] for r in llm.requests if "Нарушена" in r["messages"][-1]["content"])
    assert "Группа Складов" in retry and "без разметки" in retry
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["audit"]["unregistered_names"] == ["Группа Складов"]
