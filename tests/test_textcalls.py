# ruff: noqa: E501 — образец ответа модели: длинные строки как есть
"""Вызовы инструментов, которые модель написала текстом (playtest 2026-10-10): фаза решения их выполняет,
игроки их не видят ни в готовом ответе, ни в потоке."""

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


def test_decide_executes_calls_written_as_text(game_client, admin_g, llm, dice, settings):  # noqa: F811
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
        DONE,
        {
            "text": "Бран вышибает дверь.\naction: spawn_entity(template_id='monster.skeleton', name='Скелет')\n"
            "За дверью темно."
        },
    ]
    n = act(game_client, p1, c["id"], "Вышибаю дверь плечом")
    assert n["content"].endswith("вышибает дверь.\nЗа дверью темно.") and "spawn_entity" not in n["content"]
    # вызов из текста выполнен, модель получила результат и просьбу звать инструменты по-настоящему
    assert len(rows(settings, Event, Event.tool == "roll_check")) == 1
    note = llm.requests[1]["messages"][-1]["content"]
    assert "написал вызовы инструментов текстом" in note and '"ok": true' in note

    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["closed"] == [hero["id"]]
    assert any(t.get("from_text") for t in turn.trace["calls"])
    assert turn.trace["audit"]["tool_text"] == ["spawn_entity"]
    assert rows(settings, Event, Event.tool == "spawn_entity") == []  # в повествовании мир не меняется
