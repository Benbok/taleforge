# ruff: noqa: E501 — образец ответа модели: длинные строки как есть
"""Текстовые псевдовызовы: фаза решения отклоняет, повествование не показывает игрокам."""

import asyncio
import random

from app.agents import textcalls
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


def test_markdown_wrapped_tool_name_and_dangling_heading_are_removed():
    sample = (
        "В камере тихо.\n\n***\nВызовы, сделанные в этом ходе:\n"
        "_`describe_place` (loc_id=`en_secret`, description='камера')_\n"
        "**`reposition`** (target='ch_private', cell='corridor')\n"
    )
    assert textcalls.contains(sample, textcalls.tool_names())
    assert textcalls.clean(sample) == "В камере тихо."
    assert textcalls.clean("_`reposition` (target='ch_private'\n") == ""


def test_underscore_wrapped_name_is_recognized_without_consuming_wrapper():
    sample = "Тишина.\n_reposition_ (target='ch_private')\n"
    assert textcalls.contains(sample, {"reposition"})
    assert textcalls.strip(sample, {"reposition"}) == "Тишина."


def test_wrapped_calls_never_leak_into_fragmented_stream():
    sample = "Тишина.\nВызовы, сделанные в этом ходе:\n_`reposition` (target=`ch_private`,\ncell='secret')_\n"
    chunks = []

    async def feed():
        async def push(chunk):
            chunks.append(chunk)

        stream = textcalls.StreamFilter(push, {"reposition"})
        for char in sample:
            await stream(char)
        await stream.finish()

    asyncio.run(feed())
    assert "".join(chunks).strip() == "Тишина."


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


MARKDOWN_CALLS = """<center>
[spawn_entity](template_id="creature.skeleton", location="en_room", position={"cell":{"x":2,"y":2}}, name="Скелет 1")
[spawn_entity](template_id="creature.skeleton", location="en_room", position={"cell":{"x":3,"y":1}}, name="Скелет 2")
[resolve_attack](attacker="ch_hero", target="en_foe", weapon="inv_sword")
</center>
Кости звенят в пустом зале.
"""


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
