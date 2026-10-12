"""Checkpoint хода мастера (спецификация генерации сцен, §6.4; docs/world-objects-delivery2.md).

Версионированный JSON в ``MasterTurn.generation_checkpoint``: что уже зафиксировано и что осталось сделать.
Живых объектов ORM не содержит. ``MasterTurn.status`` по-прежнему ``running/done/failed``; этапы checkpoint:

- ``effects_committed`` — действия хода сохранены, повествования ещё нет;
- ``preparing`` — ход ждёт терминального статуса запрошенных подготовок мира;
- ``narration_pending`` — идёт или ждёт повтора описание; ``attempts`` растёт до вызова модели;
- ``done`` — текст сохранён вместе с ``done`` хода.
"""

from __future__ import annotations

from typing import Any

VERSION = 1
MAX_NARRATION_ATTEMPTS = 2
RESUMABLE = ("effects_committed", "preparing", "narration_pending")


def effects_committed(
    *,
    events: list[str],
    operation_refs: list[str],
    narration_message_id: str,
    audience: list[str] | None,
    place: str | None,
    inputs: dict[str, Any],
    reserved_fact_refs: list[str] | None = None,
    adaptation_effects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "version": VERSION,
        "stage": "effects_committed",
        "event_ids": events,
        "operation_refs": operation_refs,
        "narration_message_id": narration_message_id,
        "audience": audience,
        "place": place,
        "attempts": 0,
        "inputs": inputs,
        "reserved_fact_refs": reserved_fact_refs or [],
        "adaptation_effects": adaptation_effects or [],
    }


def resumable(cp: dict[str, Any] | None) -> bool:
    return bool(cp) and cp.get("stage") in RESUMABLE
