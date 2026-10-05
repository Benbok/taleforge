"""YAML с булевыми как в YAML 1.2: только true/false. Иначе ключ ``on`` триггеров станет ``True``.

Разбор идёт через libyaml (``CSafeLoader``), он примерно в шесть раз быстрее чистого Python: пакет правил
читается при каждом старте сервера и в каждом тесте. Если сборка PyYAML без libyaml, берётся обычный загрузчик.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_Base = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader
BOOLS = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")


class Yaml12Loader(_Base):  # type: ignore[misc,valid-type]
    pass


Yaml12Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
Yaml12Loader.add_implicit_resolver("tag:yaml.org,2002:bool", BOOLS, list("tTfF"))


def loads(text: str) -> Any:
    return yaml.load(text, Loader=Yaml12Loader)


def load_file(path: Path) -> Any:
    return loads(path.read_text(encoding="utf-8"))
