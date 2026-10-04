"""Озвучка длинного повествования по частям (вступление кампании, знакомство героев).

Один длинный синтез идёт долго, и игроки ждут молча. Поэтому текст делится на части: первая короче, чтобы голос
зазвучал как можно раньше, остальные по абзацам. Синтез части начинается, как только она дописана в потоке
модели, а записи прикрепляются к сообщению по мере готовности: data.voices — готовые по порядку,
data.voice_parts — сколько всего ждать, data.voice — первая (для старых клиентов и поиска записи).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

from sqlalchemy import update
from sqlalchemy.exc import OperationalError

from app.db.models import Message
from app.gateway.events import publish_message

log = logging.getLogger(__name__)

FIRST_MAX = 280  # первая часть: пара фраз, чтобы голос зазвучал почти сразу
PART_MAX = 700  # остальные: абзац или два
PARALLEL = 3  # одновременных синтезов на одно сообщение
SENTENCE = re.compile(r"(?<=[.!?…])\s+")

Synth = Callable[[str], Awaitable[dict | None]]


def _sentences(paragraph: str) -> list[str]:
    return [x.strip() for x in SENTENCE.split(paragraph.strip()) if x.strip()]


def _pack(pieces: list[str], limit: int, sep: str = " ") -> list[str]:
    """Жадно собирает куски в части не длиннее limit; кусок длиннее limit идёт частью сам."""
    out: list[str] = []
    for p in pieces:
        if out and len(out[-1]) + len(sep) + len(p) <= limit:
            out[-1] += sep + p
        else:
            out.append(p)
    return out


def split(text: str) -> list[str]:
    """Части для озвучки. Префикс текста даёт те же первые части: синтез можно начинать до конца потока."""
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    if not paras:
        return []
    head = _pack(_sentences(paras[0]), FIRST_MAX)
    rest = ([" ".join(head[1:])] if head[1:] else []) + paras[1:]
    pieces: list[str] = []
    for p in rest:
        pieces += [p] if len(p) <= PART_MAX else _pack(_sentences(p), PART_MAX)
    return head[:1] + _pack(pieces, PART_MAX, "\n")


class VoiceJob:
    """Синтез частей одного сообщения: feed — куски потока модели, finish — итоговый текст."""

    def __init__(self, synth: Synth, clean: Callable[[str], str] = lambda t: t) -> None:
        self.synth, self.clean = synth, clean
        self.raw = ""
        self.tasks: dict[str, asyncio.Task] = {}
        self.gate = asyncio.Semaphore(PARALLEL)

    async def _one(self, part: str) -> dict | None:
        async with self.gate:
            try:
                return await self.synth(part)
            except Exception:  # noqa: BLE001 — без одной записи текст всё равно в чате
                log.warning("озвучка части не удалась", exc_info=True)
                return None

    def _start(self, part: str) -> None:
        if part not in self.tasks:
            self.tasks[part] = asyncio.create_task(self._one(part))

    def feed(self, chunk: str) -> None:
        self.raw += chunk
        for part in split(self.clean(self.raw))[:-1]:  # последняя часть ещё дописывается
            self._start(part)

    def finish(self, text: str) -> list[asyncio.Task]:
        parts = split(text)
        for p in parts:
            self._start(p)
        for p, t in self.tasks.items():
            if p not in parts:
                t.cancel()  # начало потока разошлось с итоговым текстом
        return [self.tasks[p] for p in parts]

    def cancel(self) -> None:
        for t in self.tasks.values():
            t.cancel()


def data_of(voices: list[dict], parts: int) -> dict:
    out: dict = {"voices": voices, "voice_parts": parts}
    if voices:
        out["voice"] = voices[0]
    return out


async def _save(svc, msg: Message, data: dict) -> None:
    """Итог пишется одной записью без чтения и под замками хода и вступления той же кампании: в SQLite две
    сессии «чтение, потом запись» блокируют друг друга, и проигравшей оказалась бы чужая запись."""
    cid = msg.campaign_id
    turn = getattr(svc, "_locks", {}).setdefault(cid, asyncio.Lock())
    intro = getattr(svc, "_intro_locks", {}).setdefault(cid, asyncio.Lock())
    async with turn, intro:  # порядок как у хода: ход представляет новичка под своим замком
        for attempt in range(5):
            try:
                async with svc.maker() as s:
                    await s.execute(update(Message).where(Message.id == msg.id).values(data=data))
                    await s.commit()
                return
            except OperationalError:
                if attempt == 4:
                    raise
                await asyncio.sleep(0.2 * (attempt + 1))


async def attach(svc, msg: Message, tasks: list[asyncio.Task]) -> None:
    """Прикрепляет записи к уже опубликованному сообщению по порядку готовности: каждая часть сразу уходит
    игрокам, в базу — итог. Сообщение уже несёт voice_parts — сколько частей ждать; неудавшаяся часть
    убавляет ожидание, чтобы клиент не ждал вечно."""
    data = dict(msg.data or {})
    voices = list(data.get("voices") or [])
    parts = int(data.get("voice_parts") or len(voices) + len(tasks))
    try:
        for t in tasks:
            voice = await t
            if voice:
                voices.append(voice)
            else:
                parts -= 1
            data = {**data, **data_of(voices, parts)}
            msg.data = data
            await publish_message(svc.bus, msg)
    finally:
        for t in tasks:
            t.cancel()
    await _save(svc, msg, data)
