from types import SimpleNamespace

from app.core.map_memory import static_snapshot


def test_snapshot_is_personal_and_excludes_entities():
    place = SimpleNamespace(
        id="road",
        name="Дорога",
        kind="location",
        campaign_id="camp",
        state={
            "complex": {"root_id": "root"},
            "sketch": {
                "shape": "room",
                "cols": 3,
                "rows": 3,
                "party": [1, 1],
                "walls": [[0, 0]],
                "exits": [{"name": "Склеп", "passage_ref": "vault", "side": "e", "at": 1}],
                "features": [
                    {"name": "Колонна", "kind": "column", "cells": [[1, 1]]},
                    {"entity_id": "chest", "name": "Сундук", "kind": "object", "cells": [[2, 2]]},
                ],
            },
        },
    )
    root = SimpleNamespace(id="root", state={"blueprint": {"revision": 2}})
    snapshot = static_snapshot(
        place,
        root,
        root.state["blueprint"],
        {"chest": SimpleNamespace(id="chest", kind="object")},
        discovered_passages=frozenset({("root", "vault")}),
        revealed=frozenset(),
    )
    assert snapshot["schema_version"] == 1
    assert all("entity_id" not in feature for feature in snapshot["geometry"]["features"])
    assert "tokens" not in snapshot
    assert snapshot["geometry"]["exits"][0]["passage_ref"] == "vault"
