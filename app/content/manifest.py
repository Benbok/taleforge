"""Паспорт пакета (``pack.yaml``), ТЗ раздел 3.2."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def version_tuple(v: str) -> tuple[int, int, int]:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", v)
    if not m:
        raise ValueError(f"не версия semver: {v!r}")
    return int(m[1]), int(m[2]), int(m[3])


def version_satisfies(version: str, constraint: str) -> bool:
    """Ограничения версий зависимостей: ``*``, ``1.2.3`` (точно), ``==1.2.3``, ``>=1.2.3``."""
    c = constraint.strip()
    if c in ("", "*"):
        return True
    if c.startswith(">="):
        return version_tuple(version) >= version_tuple(c[2:].strip())
    if c.startswith("=="):
        c = c[2:].strip()
    return version_tuple(version) == version_tuple(c)


class EngineRequirements(BaseModel):
    model_config = ConfigDict(extra="allow")

    min_version: str = "0.0.0"
    ops: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)


class PackManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    version: str
    ruleset: str
    ruleset_base: str | None = None
    provides: str | None = None  # базовый пакет правил объявляет, какую базу он даёт, например srd-5.1
    depends: dict[str, str] = Field(default_factory=dict)
    engine: EngineRequirements | None = None
    excludes: list[str] = Field(default_factory=list)
    level_cap: int | None = Field(default=None, ge=1, le=20)
    languages: list[str] = Field(default_factory=lambda: ["ru"])
    license: str | None = None
    source_docs: dict[str, str] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not SEMVER.match(v):
            raise ValueError(f"версия пакета должна быть semver, получено {v!r}")
        return v
