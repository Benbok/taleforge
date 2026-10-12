"""Create deterministic, self-contained location-map examples for documentation.

The examples deliberately use the public map projection shape and contain no campaign
data, timestamps, or generated secrets.  They are useful both for visual regression
and as fixtures for the web renderer.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "examples" / "location-maps"


def sketch(name: str, *, material: str, environment: str, terrain: list[dict], exits: list[dict]) -> dict:
    return {
        "shape": "open",
        "cols": 12,
        "rows": 8,
        "party": [5, 4],
        "walls": [],
        "mask": [
            "111111111111",
            "111111111111",
            "111111111111",
            "111111111111",
            "111111111111",
            "111111111111",
            "111111111111",
            "111111111111",
        ],
        "edges": [{"side": "n", "start": 0, "length": 12, "meaning": "boundary"}],
        "terrain": terrain,
        "material": material,
        "environment": environment,
        "exits": exits,
        "features": [],
    }


def area(area_id: str, name: str, status: str, offset: list[int], level: int, current: bool, **kwargs) -> dict:
    return {
        "id": area_id,
        "name": name,
        "offset": offset,
        "level": level,
        "status": status,
        "revision": 1,
        "observed_at": None,
        "sketch": sketch(name, **kwargs),
        "disclosed_to": ["hero-a"] if current else None,
    }


def example(name: str, plan: dict) -> None:
    (OUT / f"{name}.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    road = {"kind": "road", "cells": [[x, 3] for x in range(12)] + [[x, 4] for x in range(12)]}
    stream = {"kind": "stream", "cells": [[7, y] for y in range(8)]}
    bridge = {"kind": "bridge", "cells": [[7, 3], [7, 4]]}
    exits = [
        {
            "name": "К дороге",
            "side": "w",
            "at": 3,
            "kind": "passage",
            "state": "open",
            "to": "road",
            "width": 10,
            "passage_ref": "p-road",
            "cells": [[0, 3], [0, 4]],
        }
    ]
    example(
        "field-stream-bridge",
        {
            "root_id": "demo-root",
            "here_id": "field",
            "areas": [
                area(
                    "field",
                    "Поле у ручья",
                    "here",
                    [0, 0],
                    0,
                    True,
                    material="grass",
                    environment="outdoors",
                    terrain=[road, stream, bridge],
                    exits=exits,
                )
            ],
        },
    )
    example(
        "temple-known",
        {
            "root_id": "demo-temple",
            "here_id": "sacristy",
            "areas": [
                area(
                    "sacristy",
                    "Сакристия",
                    "here",
                    [0, 0],
                    0,
                    True,
                    material="stone",
                    environment="temple",
                    terrain=[],
                    exits=exits,
                ),
                area(
                    "crypt",
                    "Склеп",
                    "remembered",
                    [16, 0],
                    -1,
                    False,
                    material="stone",
                    environment="underground",
                    terrain=[],
                    exits=[],
                ),
            ],
        },
    )
    example(
        "hero-memory",
        {
            "root_id": "demo-memory",
            "here_id": "camp",
            "areas": [
                area(
                    "camp",
                    "Лагерь",
                    "here",
                    [0, 0],
                    0,
                    True,
                    material="earth",
                    environment="outdoors",
                    terrain=[],
                    exits=[],
                ),
                area(
                    "old-road",
                    "Старая дорога",
                    "remembered",
                    [16, 0],
                    0,
                    False,
                    material="earth",
                    environment="outdoors",
                    terrain=[road],
                    exits=[],
                ),
            ],
        },
    )


if __name__ == "__main__":
    main()
