import io
import json
import types

import pytest
from PIL import Image

from app.config import Settings
from app.core import map_backdrop as backdrop
from app.core.artwork import service
from app.db.models import Entity


def sketch(**over):
    base = {
        "shape": "open", "cols": 10, "rows": 8, "party": [3, 3], "walls": [], "mask": None, "edges": [],
        "terrain": [{"kind": "road", "cells": [[4, 0, 4, 7]]}], "material": "grass", "environment": "outdoor",
        "exits": [
            {"name": "Дверь", "side": "n", "at": 5, "kind": "door", "to": "SECRET-ROOM"},
            {"name": "Тайный ход", "side": "w", "at": 2, "kind": "door", "hidden": True},
        ],
        "features": [{"name": "SECRET-TRAP", "kind": "object", "cells": [[2, 2, 2, 2]], "hidden": True}],
        "unplaced_exits": [{"name": "SECRET-UNPLACED"}],
    }
    return {**base, **over}


def area(**over):
    state = {"secret": "SECRET-RUINS", "sketch": sketch()}
    return Entity(id="bd_room", campaign_id="c", kind="location", name="Двор", description="Двор таверны.",
                  state={**state, **over})


def viewer(role=None):
    return types.SimpleNamespace(
        campaign=types.SimpleNamespace(id="c", ruleset_id="universal", name="Игра"),
        user=types.SimpleNamespace(platform_role=role or "user"),
    )


def test_source_excludes_hidden_exit_features_and_secrets():
    source = backdrop.source(viewer(), area())
    prompt = backdrop.RECIPE.prompt_source(source)
    assert "SECRET" not in json.dumps(source, ensure_ascii=False) and "Тайный ход" not in json.dumps(source)
    assert set(prompt) == {"identity", "appearance", "personality"}
    assert prompt["identity"] == "Двор" and prompt["appearance"] == "Двор таверны."
    assert "SECRET" not in json.dumps(prompt)
    init = Image.open(io.BytesIO(backdrop.RECIPE.init_image(source)))
    assert init.size == (768, 640)


@pytest.mark.parametrize("role", [None, "player"])
def test_non_admin_is_not_permitted(role):
    assert backdrop.RECIPE.permitted(viewer(role)) is False


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_admin_is_permitted(role):
    assert backdrop.RECIPE.permitted(viewer(role)) is True


def test_blocker_needs_description_and_sketch():
    recipe = backdrop.RECIPE
    assert recipe.blocker(backdrop.source(viewer(), area())) is None
    no_description = area()
    no_description.description = " "
    assert "описания" in recipe.blocker(backdrop.source(viewer(), no_description))
    no_sketch = area(sketch=None)
    assert "схему" in recipe.blocker(backdrop.source(viewer(), no_sketch))


def test_digest_changes_when_hidden_exit_becomes_visible():
    revealed = sketch()
    revealed["exits"][1]["hidden"] = False
    before = service.digest(backdrop.source(viewer(), area()))
    assert service.digest(backdrop.source(viewer(), area(sketch=revealed))) != before
    moved_party = sketch(party=[6, 6])
    assert service.digest(backdrop.source(viewer(), area(sketch=moved_party))) == before


def test_url_points_to_map_backdrop_route():
    assert backdrop.RECIPE.url("c1", "loc1", "aw_1") == "/api/campaigns/c1/locations/loc1/map-backdrop/aw_1"


def test_config_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("MAP_BACKDROP_ENABLED", raising=False)
    assert Settings.from_env().map_backdrop_enabled is False
    monkeypatch.setenv("MAP_BACKDROP_ENABLED", "1")
    assert Settings.from_env().map_backdrop_enabled is True


def test_blueprint_backed_area_is_blocked_because_passage_state_lives_on_the_root():
    complex_area = area(sketch=sketch(blueprint={"root_id": "root"}))
    source = backdrop.source(viewer(), complex_area)
    assert "комплекс" in backdrop.RECIPE.blocker(source)
    assert backdrop.RECIPE.init_image(source) is None


PASSAGES = [
    {"name": "Дворовые ворота", "side": "n"},
    {"name": "Старая тропа", "side": "n"},
    {"name": "Пролаз в изгороди", "side": "w"},
    {"name": "Колея на восток", "side": "e"},
]


def test_visible_passages_become_exits_spread_along_their_side():
    exits = backdrop.source(viewer(), area(), PASSAGES)["sketch"]["exits"]
    synthesized = [e for e in exits if e["kind"] == "passage"]
    north = sorted(e["at"] for e in synthesized if e["side"] == "n")
    assert len(synthesized) == 4 and len(north) == 2 and 0 <= north[0] < north[1] <= 8
    west = next(e for e in synthesized if e["side"] == "w")
    assert west["at"] == 3 and west["width"] == 2  # centred on an 8-row side
    assert "Тайный ход" not in json.dumps(exits, ensure_ascii=False)


def test_prompt_lists_exits_by_picture_edge_and_digest_follows_them():
    source = backdrop.source(viewer(), area(), PASSAGES)
    appearance = backdrop.RECIPE.prompt_source(source)["appearance"]
    assert appearance.startswith("Двор таверны.")
    assert "слева" in appearance and "Пролаз в изгороди" in appearance and "сверху" in appearance
    assert "SECRET" not in appearance
    assert service.digest(source) != service.digest(backdrop.source(viewer(), area(), PASSAGES[:2]))
    assert backdrop.RECIPE.prompt_source(backdrop.source(viewer(), area()))["appearance"] == "Двор таверны."


def test_side_of_bearing_matches_the_client_rules():
    assert [backdrop.side_of(b) for b in ("ne", "w", "sw", "n", None, "s")] == ["e", "w", "w", "n", "n", "s"]
