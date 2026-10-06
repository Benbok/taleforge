"""Контракт сервера для клиента: OpenAPI-схема REST и событий WebSocket.

``python -m app.contract`` записывает схему в ``web/openapi.json``; из неё ``npm run gen:api`` строит типы клиента
(``web/src/lib/api.gen.ts``). Тест ``tests/test_contract.py`` проверяет, что записанная схема не устарела.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.config import Settings
from app.gateway.protocol import ServerEvent

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "web" / "openapi.json"


def schema() -> dict[str, Any]:
    from app.main import create_app

    app = create_app(Settings(database_url="sqlite+aiosqlite://", jwt_secret="contract-" * 4))
    doc = app.openapi()
    schemas = doc.setdefault("components", {}).setdefault("schemas", {})
    events = TypeAdapter(ServerEvent).json_schema(ref_template="#/components/schemas/{model}", mode="validation")
    for name, definition in events.pop("$defs").items():
        # модели героя общие у REST и событий: FastAPI описывает их так же, только без additionalProperties и default
        if name in schemas and _bare(schemas[name]) != _bare(definition):
            raise RuntimeError(f"имя схемы {name!r} занято и REST, и событием WebSocket")
        schemas[name] = definition
    schemas["ServerEvent"] = events
    return doc


def _bare(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _bare(v) for k, v in x.items() if k not in ("additionalProperties", "default")}
    if isinstance(x, list):
        return [_bare(v) for v in x]
    return x


def render() -> str:
    return json.dumps(schema(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"


if __name__ == "__main__":
    out = render()
    if "--check" in sys.argv:
        if SCHEMA_PATH.read_text(encoding="utf-8") != out:
            sys.exit("web/openapi.json устарел: запустите python -m app.contract")
    else:
        SCHEMA_PATH.write_text(out, encoding="utf-8")
