"""Контракты подготовки сцены (§4.3): план выдаёт сервер, предложение только заполняет его слоты."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

POLICY_VERSION = "scene-policy-v1"
PRNG = "py-mt-v1"  # random.Random (Mersenne Twister): другую сохранённую версию воспроизвести нельзя
PHASES = ("location_initial", "container_contents")

Role = Literal["prop", "container", "item"]


class Blocked(Exception):
    """Диагностируемая причина, по которой фаза становится ``blocked``."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Slot:
    """Стабильное место в плане: id назначает policy, не модель."""

    slot_ref: str
    role: Role
    name: str
    description: str = ""
    template_id: str | None = None
    cost: int = 0
    zone: str = "near"
    visual_key: str | None = None
    parent: str | None = None  # slot_ref контейнера внутри этого же плана


@dataclass
class Plan:
    phase: str
    target_id: str
    reservation: dict[str, Any]
    slots: list[Slot] = field(default_factory=list)
    children: dict[str, dict[str, Any]] = field(default_factory=dict)  # slot_ref контейнера → его резерв
    spent: int = 0

    def slot(self, ref: str) -> Slot | None:
        return next((s for s in self.slots if s.slot_ref == ref), None)


@dataclass(frozen=True)
class ProposedObject:
    slot_ref: str
    role: Role
    name: str
    description: str = ""
    template_id: str | None = None


@dataclass(frozen=True)
class Proposal:
    schema_version: int
    objects: tuple[ProposedObject, ...]


def digest(data: Any) -> str:
    """Каноническая сериализация для диагностики и сравнения снимков; не замена CAS."""
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
