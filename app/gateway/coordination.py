"""Согласование внутри сервера: замки кампаний и открытые кнопки реакций.

Сервер рассчитан на один процесс: ход кампании идёт под замком, а кнопку реакции ждёт корутина этого же
процесса. Всё такое состояние собрано здесь, за интерфейсом ``Coordination``, чтобы для нескольких процессов
хватило одной новой реализации (замки — в Redis или advisory locks PostgreSQL, ответы на кнопки — через шину),
а не правок по всему коду. Поэтому новое состояние, которое нельзя потерять при перезапуске или нужно видеть
из другого процесса, кладётся сюда или в БД, но не в поля сервисов.

Что ещё живёт в памяти процесса и переносится тем же путём: очередь ходов и фоновые задачи
(``MasterService``), таймеры хода в бою, таймеры ухода и голосования (``app/gateway/presence.py``), сроки
голосований за отдых (``app/gateway/rest.py``, сами голоса — в состоянии сцены) и кэш каталога пакетов
(``app/content/catalog.py``).
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol


class Coordination(Protocol):
    """Замки кампаний и ожидание ответа на кнопку реакции."""

    def turn_lock(self, campaign_id: str) -> asyncio.Lock:
        """Замок хода: под ним идут ход мастера, ходы существ и запись итогов озвучки."""
        ...

    def intro_lock(self, campaign_id: str) -> asyncio.Lock:
        """Замок вступления: мастер представляет новичка и кампанию под ним."""
        ...

    def whisper_lock(self, campaign_id: str) -> asyncio.Lock:
        """Замок ответов на шёпот: мастер отвечает на шёпоты кампании по одному."""
        ...

    def open_prompt(self, prompt_id: str, campaign_id: str, seat_id: str) -> asyncio.Future:
        """Открыть кнопку реакции и получить ожидание ответа."""
        ...

    def describe_prompt(self, prompt_id: str, payload: dict[str, Any]) -> None:
        """Описание кнопки: его отдаёт снимок состояния игроку, переподключившемуся с открытой кнопкой."""
        ...

    def close_prompt(self, prompt_id: str) -> None: ...

    def answer_prompt(self, prompt_id: str, seat_id: str | None, option: str) -> bool:
        """Ответ игрока. False — кнопки нет, она чужая или ответ уже принят."""
        ...

    def pending_prompt(self, campaign_id: str, seat_id: str | None) -> dict[str, Any] | None:
        """Открытая кнопка реакции этого места, если есть."""
        ...


class InMemoryCoordination:
    """Согласование в памяти процесса: годится, пока сервер один (см. docstring модуля)."""

    def __init__(self) -> None:
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        # prompt_id → (кампания, место, ответ, описание кнопки)
        self._prompts: dict[str, tuple[str, str, asyncio.Future, dict[str, Any] | None]] = {}

    def _lock(self, kind: str, campaign_id: str) -> asyncio.Lock:
        return self._locks.setdefault((kind, campaign_id), asyncio.Lock())

    def turn_lock(self, campaign_id: str) -> asyncio.Lock:
        return self._lock("turn", campaign_id)

    def intro_lock(self, campaign_id: str) -> asyncio.Lock:
        return self._lock("intro", campaign_id)

    def whisper_lock(self, campaign_id: str) -> asyncio.Lock:
        return self._lock("whisper", campaign_id)

    def open_prompt(self, prompt_id: str, campaign_id: str, seat_id: str) -> asyncio.Future:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._prompts[prompt_id] = (campaign_id, seat_id, fut, None)
        return fut

    def describe_prompt(self, prompt_id: str, payload: dict[str, Any]) -> None:
        cid, seat_id, fut, _ = self._prompts[prompt_id]
        self._prompts[prompt_id] = (cid, seat_id, fut, payload)

    def close_prompt(self, prompt_id: str) -> None:
        self._prompts.pop(prompt_id, None)

    def answer_prompt(self, prompt_id: str, seat_id: str | None, option: str) -> bool:
        entry = self._prompts.get(prompt_id)
        if entry is None or entry[1] != seat_id or entry[2].done():
            return False
        entry[2].set_result(option)
        return True

    def pending_prompt(self, campaign_id: str, seat_id: str | None) -> dict[str, Any] | None:
        for cid, seat, fut, payload in self._prompts.values():
            if cid == campaign_id and seat == seat_id and payload is not None and not fut.done():
                return payload
        return None
