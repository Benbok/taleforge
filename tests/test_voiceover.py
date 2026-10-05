"""Озвучка длинного повествования по частям и чистка текста вступления."""

import asyncio

import pytest

from app.agents import voiceover
from app.agents.prelude import clean_story

PARA1 = (
    "Железный Конкордат стоял, словно серый колосс. Его границы начертаны кровью забытых войн. "
    "Над шпилями висит дым литейных. В порту скрипят цепи кораблей. Ветер несёт запах соли и угля."
)
PARA2 = "Вы приходите в себя в холодной камере. Снаружи слышны крики и грохот."
PARA3 = "Дверь камеры приоткрыта, за ней — тёмный коридор и мерцающий фонарь."


def test_split_first_part_short_rest_by_paragraphs():
    text = "\n\n".join([PARA1, PARA2, PARA3])
    parts = voiceover.split(text)
    assert len(parts[0]) <= voiceover.FIRST_MAX and PARA1.startswith(parts[0])
    assert all(len(p) <= voiceover.PART_MAX for p in parts)
    # ни одно слово не потеряно и порядок тот же
    assert " ".join(" ".join(parts).split()) == " ".join(text.split())


def test_split_prefix_stable():
    """Части, дописанные в потоке, совпадают с частями итогового текста: синтез можно начать заранее."""
    text = "\n\n".join([PARA1, PARA2 * 5, PARA3])
    final = voiceover.split(text)
    for cut in range(10, len(text), 37):
        early = voiceover.split(text[:cut])[:-1]
        assert early == final[: len(early)]


def test_clean_story_drops_heading_and_echo():
    raw = "*Масштабное и атмосферное художественное вступление к кампании:*\n\n" + PARA1
    assert clean_story(raw) == PARA1
    assert clean_story("## Пролог\n" + PARA2) == PARA2
    assert clean_story("Кампания «Заключённый». Завязка: " + PARA2) == PARA2
    assert clean_story("Кампания «Заключённый». " + PARA2) == PARA2
    # одна строка в потоке ещё пишется — её не трогаем; обычный текст остаётся как есть
    assert clean_story("*Масштабное и атмосферное") == "*Масштабное и атмосферное"
    assert clean_story(PARA1 + "\n\n" + PARA2) == PARA1 + "\n\n" + PARA2
    # чужая разметка снимается, разметка героев остаётся
    assert (
        clean_story("[[hero1|Бран]] и [[x|незнакомец]]", keep=lambda ref: ref == "hero1")
        == "[[hero1|Бран]] и незнакомец"
    )


@pytest.mark.anyio
async def test_voice_job_starts_parts_while_streaming():
    started: list[str] = []

    async def synth(part: str) -> dict:
        started.append(part)
        await asyncio.sleep(0)
        return {"id": f"v{len(started)}", "duration": 1.0}

    job = voiceover.VoiceJob(synth, clean_story)
    text = "\n\n".join([PARA1, PARA2, PARA3])
    job.feed("*Вступление:*\n\n")
    for i in range(0, len(text), 40):
        job.feed(text[i : i + 40])
        await asyncio.sleep(0)
    assert started and started[0] == voiceover.split(text)[0]  # первая часть ушла в синтез до конца потока
    voices = await asyncio.gather(*job.finish(clean_story("*Вступление:*\n\n" + text)))
    assert len(voices) == len(voiceover.split(text)) and len(set(started)) == len(started)  # без повторов


@pytest.mark.anyio
async def test_voice_job_failed_part_is_none():
    async def synth(part: str) -> dict:
        raise RuntimeError("TTS недоступен")

    job = voiceover.VoiceJob(synth)
    assert await asyncio.gather(*job.finish(PARA2)) == [None]


def test_data_of():
    assert voiceover.data_of([], 3) == {"voices": [], "voice_parts": 3}
    v = {"id": "a", "duration": 2.0}
    assert voiceover.data_of([v], 2) == {"voices": [v], "voice_parts": 2, "voice": v}


@pytest.mark.anyio
async def test_story_feed_hides_heading_in_draft():
    """Черновик в чате уже без служебного заголовка: первая строка ждёт перевода строки."""
    from app.agents.prelude import StoryFeed

    shown: list[str] = []

    class FakeStream:
        async def push(self, chunk: str) -> None:
            shown.append(chunk)

        async def reset(self) -> None:
            shown.clear()

    feed = StoryFeed(FakeStream(), None)
    for chunk in ["*Масштабное вступ", "ление к кампании:*", "\n\nЖелезный Конкордат", " стоит."]:
        await feed.push(chunk)
    assert "".join(shown) == "Железный Конкордат стоит."
