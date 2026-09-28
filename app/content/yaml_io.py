"""YAML с булевыми как в YAML 1.2: только true/false. Иначе ключ ``on`` триггеров станет ``True``."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


class Yaml12Loader(yaml.SafeLoader):
    pass


Yaml12Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
Yaml12Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def loads(text: str) -> Any:
    return yaml.load(text, Loader=Yaml12Loader)


def load_file(path: Path) -> Any:
    return loads(path.read_text(encoding="utf-8"))
